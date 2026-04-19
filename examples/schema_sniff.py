# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "textual"]
# ///
"""Infer and display payload schemas per event_type, live.

Subscribes to `discord.>` and accumulates observed payload structure per
`event_type`. Renders a scrollable tree: each field shows its type union,
occurrence rate, and an example. Dict and list fields are expandable so
you can drill into nested structure (e.g. `author`, `mentions`, `member`).
List element shapes are aggregated under `[items]`.

Press `s` to save the current schemas to the file given by --output.
On quit, the file is written automatically if --output was provided.

Run:
    uv run --script examples/schema_sniff.py
    uv run --script examples/schema_sniff.py --output docs/schemas.md
    uv run --script examples/schema_sniff.py --format ts --output docs/schemas.ts
    uv run --script examples/schema_sniff.py --format json --output docs/schemas.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import nats
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.>"
REFRESH_INTERVAL = 1.0
EXAMPLE_MAX = 60
MAX_DEPTH = 5

TYPE_COLORS: dict[str, str] = {
    "null": "red",
    "bool": "magenta",
    "int": "cyan",
    "float": "cyan",
    "str": "green",
    "list": "yellow",
    "dict": "blue",
}


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def style_types(types: set[str]) -> str:
    return "[dim]|[/dim]".join(f"[{TYPE_COLORS.get(t, 'white')}]{t}[/]" for t in sorted(types))


def style_pct(pct: int) -> str:
    if pct == 100:
        return f"[bold green]{pct}%[/]"
    if pct >= 50:
        return f"[yellow]{pct}%[/]"
    return f"[dim]{pct}%[/dim]"


def truncate_example(v: Any) -> str:
    s = repr(v)
    return s if len(s) <= EXAMPLE_MAX else s[: EXAMPLE_MAX - 1] + "…"


class FieldStats:
    __slots__ = ("count", "example", "items", "subfields", "types")

    def __init__(self) -> None:
        self.count: int = 0
        self.types: set[str] = set()
        self.example: Any = None
        self.subfields: dict[str, FieldStats] = {}
        self.items: FieldStats | None = None

    def observe(self, value: Any) -> None:
        self.count += 1
        self.types.add(type_name(value))
        if value not in (None, "", [], {}) and self.example in (None, "", [], {}):
            self.example = value
        if isinstance(value, dict):
            for k, v in value.items():
                child = self.subfields.get(k)
                if child is None:
                    child = FieldStats()
                    self.subfields[k] = child
                child.observe(v)
        elif isinstance(value, list):
            if self.items is None:
                self.items = FieldStats()
            for item in value:
                self.items.observe(item)


def _md_table(
    fields: dict[str, FieldStats], parent_count: int, has_children_set: set[str]
) -> list[str]:
    lines = ["| Field | Types | % | Example |", "|---|---|---|---|"]
    for fname in sorted(fields):
        fs = fields[fname]
        types = "|".join(sorted(fs.types))
        pct = 100 * fs.count // max(parent_count, 1)
        if fname in has_children_set:
            example = "_see below_"
        else:
            example = f"`{truncate_example(fs.example)}`"
        lines.append(f"| `{fname}` | {types} | {pct}% | {example} |")
    return lines


def _md_sections(
    fields: dict[str, FieldStats],
    parent_count: int,
    path: str,
    depth: int,
    out: list[str],
) -> None:
    if depth > MAX_DEPTH:
        return
    for fname in sorted(fields):
        fs = fields[fname]
        has_children = bool(fs.subfields) or fs.items is not None
        if not has_children:
            continue
        section_path = f"{path}.{fname}"
        heading = "###" if depth == 1 else "####"
        if fs.subfields:
            out.append(f"\n{heading} `{section_path}` (dict)\n")
            out.append(f"_{fs.count} observations._\n")
            child_has_children = {k for k, v in fs.subfields.items() if v.subfields or v.items}
            out.extend(_md_table(fs.subfields, fs.count, child_has_children))
            _md_sections(fs.subfields, fs.count, section_path, depth + 1, out)
        if fs.items is not None:
            items_path = f"{section_path}[]"
            out.append(f"\n{heading} `{items_path}` (list items)\n")
            out.append(f"_{fs.items.count} items observed._\n")
            if fs.items.subfields:
                child_has_children = {
                    k for k, v in fs.items.subfields.items() if v.subfields or v.items
                }
                out.extend(_md_table(fs.items.subfields, fs.items.count, child_has_children))
                _md_sections(fs.items.subfields, fs.items.count, items_path, depth + 1, out)
            elif fs.items.types:
                types = "|".join(sorted(fs.items.types))
                out.append(f"\nScalar items: `{types}`")
                if fs.items.example is not None:
                    out.append(f", e.g. `{truncate_example(fs.items.example)}`")
                out.append("\n")


_TS_TYPE: dict[str, str] = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "null": "null",
    "list": "unknown[]",
    "dict": "Record<string, unknown>",
}


def _ts_type(types: set[str]) -> str:
    mapped = dict.fromkeys(_TS_TYPE.get(t, "unknown") for t in sorted(types))
    return " | ".join(mapped)


def _ts_fields(
    fields: dict[str, FieldStats], parent_count: int, depth: int, indent: int
) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    for fname in sorted(fields):
        fs = fields[fname]
        pct = 100 * fs.count // max(parent_count, 1)
        optional = "?" if pct < 100 else ""
        comment = f"  // {pct}%" if pct < 100 else ""
        has_children = bool(fs.subfields) or fs.items is not None
        if depth >= MAX_DEPTH or not has_children:
            lines.append(f"{pad}{fname}{optional}: {_ts_type(fs.types)};{comment}")
        elif fs.subfields:
            lines.append(f"{pad}{fname}{optional}: {{{comment}")
            lines.extend(_ts_fields(fs.subfields, fs.count, depth + 1, indent + 1))
            lines.append(f"{pad}}};")
        elif fs.items is not None:
            items = fs.items
            if items.subfields:
                lines.append(f"{pad}{fname}{optional}: Array<{{{comment}")
                lines.extend(_ts_fields(items.subfields, items.count, depth + 1, indent + 1))
                lines.append(f"{pad}}}>; ")
            else:
                lines.append(f"{pad}{fname}{optional}: Array<{_ts_type(items.types)}>;{comment}")
    return lines


def build_typescript(stats: dict[str, FieldStats]) -> str:
    total = sum(s.count for s in stats.values())
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "// Discord event payload schemas",
        f"// Generated by examples/schema_sniff.py at {ts}",
        f"// {total} events across {len(stats)} types",
        "// Optional fields (?) were absent in some observed events.",
        "",
    ]
    for etype in sorted(stats):
        s = stats[etype]
        lines.append(f"// {s.count} events observed")
        lines.append(f"interface {etype} {{")
        lines.extend(_ts_fields(s.subfields, s.count, 1, 1))
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _fs_to_dict(fs: FieldStats, parent_count: int, depth: int) -> dict[str, Any]:
    pct = 100 * fs.count // max(parent_count, 1)
    node: dict[str, Any] = {
        "types": sorted(fs.types),
        "count": fs.count,
        "pct": pct,
    }
    if fs.example not in (None, "", [], {}):
        node["example"] = truncate_example(fs.example)
    if depth < MAX_DEPTH:
        if fs.subfields:
            node["fields"] = {
                k: _fs_to_dict(v, fs.count, depth + 1) for k, v in sorted(fs.subfields.items())
            }
        if fs.items is not None:
            node["items"] = _fs_to_dict(fs.items, fs.count, depth + 1)
    return node


def build_json(stats: dict[str, FieldStats]) -> str:
    total = sum(s.count for s in stats.values())
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict[str, Any] = {
        "_meta": {"generated_at": ts, "total_events": total, "event_types": len(stats)},
    }
    for etype in sorted(stats):
        s = stats[etype]
        out[etype] = {
            "_count": s.count,
            **{k: _fs_to_dict(v, s.count, 1) for k, v in sorted(s.subfields.items())},
        }
    return json.dumps(out, indent=2, ensure_ascii=False)


def build_markdown(stats: dict[str, FieldStats]) -> str:
    total = sum(s.count for s in stats.values())
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        "# Discord event payload schemas\n",
        f"_Generated by `examples/schema_sniff.py` at {ts}. "
        f"{total} events across {len(stats)} types._\n",
    ]
    for etype in sorted(stats):
        s = stats[etype]
        lines.append(f"\n## {etype}\n")
        lines.append(f"_{s.count} events observed._\n")
        has_children = {k for k, v in s.subfields.items() if v.subfields or v.items}
        lines.extend(_md_table(s.subfields, s.count, has_children))
        _md_sections(s.subfields, s.count, etype, 1, lines)
    return "\n".join(lines) + "\n"


class SchemaSniffApp(App[None]):
    TITLE = "discord-proxy · payload schemas"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("s", "save", "Save"),
    ]
    CSS = "Tree { height: 1fr; }"

    def __init__(self, output_path: Path | None = None, output_format: str = "md") -> None:
        super().__init__()
        self.stats: dict[str, FieldStats] = defaultdict(FieldStats)
        self.nodes: dict[tuple[str, ...], TreeNode] = {}
        self.output_path = output_path
        self.output_format = output_format
        self.nc: nats.NATS | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Tree("schemas", id="schemas")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one(Tree).root.expand()
        self.nc = await nats.connect(NATS_URL)
        await self.nc.subscribe(SUBJECT, cb=self._on_msg)
        self.set_interval(REFRESH_INTERVAL, self._refresh)

    async def _on_msg(self, msg: nats.aio.msg.Msg) -> None:
        try:
            env = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        etype = env.get("event_type")
        payload = env.get("payload")
        if isinstance(etype, str) and isinstance(payload, dict):
            self.stats[etype].observe(payload)

    def action_save(self) -> None:
        if self.output_path is None:
            self.notify("No --output path set.", severity="warning")
            return
        self._write_markdown(self.output_path)
        self.notify(f"Saved to {self.output_path}")

    def _write_markdown(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        builders = {"md": build_markdown, "ts": build_typescript, "json": build_json}
        path.write_text(builders[self.output_format](self.stats), encoding="utf-8")

    def _refresh(self) -> None:
        tree = self.query_one(Tree)
        total_events = sum(s.count for s in self.stats.values())
        tree.root.label = (
            f"[bold]schemas[/bold]  [dim]({total_events} events, {len(self.stats)} types)[/dim]"
        )
        for etype in sorted(self.stats):
            s = self.stats[etype]
            etype_path = (etype,)
            node = self.nodes.get(etype_path)
            if node is None:
                node = tree.root.add("", expand=True)
                self.nodes[etype_path] = node
            node.label = f"[bold yellow]{etype}[/]  [dim]({s.count})[/dim]"
            for fname in sorted(s.subfields):
                self._render_field(node, (*etype_path, fname), fname, s.subfields[fname], s.count)

    def _render_field(
        self,
        parent_node: TreeNode,
        path: tuple[str, ...],
        fname: str,
        fs: FieldStats,
        parent_count: int,
        is_items: bool = False,
    ) -> None:
        has_children = bool(fs.subfields) or fs.items is not None
        types_str = style_types(fs.types)
        if is_items:
            stat_str = f"[dim]({fs.count} items)[/]"
        else:
            pct = 100 * fs.count // max(parent_count, 1)
            stat_str = style_pct(pct)

        label = f"[bold cyan]{fname}[/]: {types_str}  {stat_str}"
        if not has_children:
            label += f"  [dim green]{truncate_example(fs.example)}[/]"

        node = self.nodes.get(path)
        if node is None:
            node = (
                parent_node.add(label, expand=False)
                if has_children
                else parent_node.add_leaf(label)
            )
            self.nodes[path] = node
        else:
            node.label = label

        if has_children:
            for sub_name in sorted(fs.subfields):
                self._render_field(
                    node, (*path, sub_name), sub_name, fs.subfields[sub_name], fs.count
                )
            if fs.items is not None:
                self._render_field(
                    node, (*path, "[items]"), "[items]", fs.items, fs.count, is_items=True
                )

    async def on_unmount(self) -> None:
        if self.output_path is not None:
            self._write_markdown(self.output_path)
        if self.nc is not None:
            await self.nc.drain()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--format", choices=("md", "ts", "json"), default="md")
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    SchemaSniffApp(output_path=args.output, output_format=args.format).run()
