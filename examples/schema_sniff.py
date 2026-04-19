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

Run:
    uv run --script examples/schema_sniff.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, ClassVar

import nats
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.>"
REFRESH_INTERVAL = 1.0
EXAMPLE_MAX = 60

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


class SchemaSniffApp(App[None]):
    TITLE = "discord-proxy · payload schemas"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]
    CSS = "Tree { height: 1fr; }"

    def __init__(self) -> None:
        super().__init__()
        self.stats: dict[str, FieldStats] = defaultdict(FieldStats)
        self.nodes: dict[tuple[str, ...], TreeNode] = {}
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
        if self.nc is not None:
            await self.nc.drain()


if __name__ == "__main__":
    SchemaSniffApp().run()
