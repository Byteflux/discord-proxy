# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "rich"]
# ///
"""Observe unclassified Discord REST traffic and propose route classifications.

Subscribes to `discord.rest.unclassified.>`, accumulates (method, template)
pairs, infers semantic ID names by cross-referencing path snowflakes against
response body fields, and renders a ranked live table.

Press Ctrl-C to exit; if --output is set the report is written on exit.

Run:
    uv run --script examples/rest_classify_sniff.py
    uv run --script examples/rest_classify_sniff.py --output candidates.py --format py
    uv run --script examples/rest_classify_sniff.py --output candidates.md --format md
    uv run --script examples/rest_classify_sniff.py --min-hits 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nats
import nats.aio.msg
from rich.console import Console
from rich.live import Live
from rich.table import Table

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.rest.unclassified.>"
REFRESH_INTERVAL = 1.0
CONFIDENCE_THRESHOLD = 0.6
BODY_SIZE_CAP = 2048

_VERSION_RE = re.compile(r"^/api/v\d+")

_SEGMENT_TO_ROLE: dict[str, str] = {
    "guilds": "guild_id",
    "channels": "channel_id",
    "messages": "message_id",
    "members": "user_id",
    "users": "user_id",
    "roles": "role_id",
    "emojis": "emoji_id",
    "stickers": "sticker_id",
    "threads": "channel_id",
    "webhooks": "webhook_id",
}


@dataclass
class RouteStats:
    count: int = 0
    status_counts: Counter[int] = field(default_factory=Counter)
    sample_path: str = ""
    sample_body: str = ""
    slot_roles: list[Counter[str]] = field(default_factory=list)


def _strip_version(path: str) -> str:
    m = _VERSION_RE.match(path)
    return path[m.end() :] if m else path


def _extract_slot_ids(template: str, path: str) -> list[str]:
    t_segs = template.lstrip("/").split("/")
    p_segs = _strip_version(path).lstrip("/").split("/")
    if len(t_segs) != len(p_segs):
        return []
    return [p for t, p in zip(t_segs, p_segs, strict=True) if t == "{id}"]


def _prior_for_slot(template: str, slot_index: int) -> str:
    segs = template.lstrip("/").split("/")
    count = 0
    for i, seg in enumerate(segs):
        if seg == "{id}":
            if count == slot_index:
                prev = segs[i - 1] if i > 0 else ""
                return _SEGMENT_TO_ROLE.get(prev, "id")
            count += 1
    return "id"


def _body_votes(body: dict[str, Any]) -> dict[str, str]:
    """Map {snowflake_value: role_name} from explicitly named body fields."""
    result: dict[str, str] = {}

    def _maybe(role: str, val: Any) -> None:
        if isinstance(val, str) and len(val) >= 17 and val.isdigit():
            result[val] = role

    _maybe("guild_id", body.get("guild_id"))
    _maybe("channel_id", body.get("channel_id"))
    _maybe("user_id", body.get("user_id"))
    _maybe("message_id", body.get("message_id"))
    _maybe("role_id", body.get("role_id"))
    author = body.get("author")
    if isinstance(author, dict):
        _maybe("user_id", author.get("id"))
    return result


def observe(
    stats: RouteStats,
    template: str,
    path: str,
    status: int,
    body: Any,
) -> None:
    stats.count += 1
    stats.status_counts[status] += 1
    if not stats.sample_path:
        stats.sample_path = path

    segs = template.lstrip("/").split("/")
    n_slots = segs.count("{id}")

    if not stats.slot_roles:
        stats.slot_roles = [Counter() for _ in range(n_slots)]
        for i in range(n_slots):
            stats.slot_roles[i][_prior_for_slot(template, i)] += 1

    if not stats.sample_body and isinstance(body, (dict, list)) and 200 <= status < 300:
        raw = json.dumps(body, ensure_ascii=False)
        stats.sample_body = raw[:BODY_SIZE_CAP] + ("…" if len(raw) > BODY_SIZE_CAP else "")

    if not (200 <= status < 300 and isinstance(body, dict) and n_slots > 0):
        return

    slot_ids = _extract_slot_ids(template, path)
    if len(slot_ids) != n_slots:
        return

    votes = _body_votes(body)
    for i, sid in enumerate(slot_ids):
        if sid in votes:
            stats.slot_roles[i][votes[sid]] += 1


def _proposed(template: str, slot_roles: list[Counter[str]]) -> tuple[str, list[str], float]:
    """Return (proposed_template, groups, min_confidence)."""
    if not slot_roles:
        return template, [], 1.0
    proposed_segs: list[str] = []
    groups: list[str] = []
    min_conf = 1.0
    slot_idx = 0
    for seg in template.lstrip("/").split("/"):
        if seg == "{id}":
            c = slot_roles[slot_idx]
            total = sum(c.values())
            winner, top = c.most_common(1)[0]
            conf = top / total if total > 0 else 0.0
            min_conf = min(min_conf, conf)
            display = winner if conf >= CONFIDENCE_THRESHOLD else f"{winner}?"
            proposed_segs.append("{" + display + "}")
            groups.append(winner)
            slot_idx += 1
        else:
            proposed_segs.append(seg)
    return "/" + "/".join(proposed_segs), groups, min_conf


def _tmpl_to_raw_pattern(proposed_template: str) -> str:
    inner = re.sub(r"\{[^}]+\}", lambda _: r"(\d+)", proposed_template.lstrip("/"))
    return r"^/api/v\d+/" + inner + r"$"


def _status_mix(counts: Counter[int]) -> str:
    return " ".join(f"{k}:{v}" for k, v in sorted(counts.items())[:3])


def build_table(stats_map: dict[tuple[str, str], RouteStats], min_hits: int) -> Table:
    table = Table(
        title=f"unclassified REST routes  [dim](min-hits={min_hits})[/]",
        show_header=True,
        header_style="bold",
        expand=True,
    )
    table.add_column("Hits", justify="right", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Method", style="bold yellow", no_wrap=True)
    table.add_column("Proposed template", ratio=3)
    table.add_column("Sample path", ratio=2)

    for (method, template), s in sorted(stats_map.items(), key=lambda kv: -kv[1].count):
        if s.count < min_hits:
            continue
        prop_tmpl, _, conf = _proposed(template, s.slot_roles)
        color = "green" if conf >= CONFIDENCE_THRESHOLD else "yellow"
        table.add_row(
            str(s.count),
            _status_mix(s.status_counts),
            method,
            f"[{color}]{prop_tmpl}[/]",
            s.sample_path,
        )
    return table


def build_py(stats_map: dict[tuple[str, str], RouteStats], min_hits: int) -> str:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# Generated by examples/rest_classify_sniff.py at {ts}",
        "# Review and paste into src/discord_proxy/rest/routes.py",
        "",
    ]
    rows = sorted(
        [(k, v) for k, v in stats_map.items() if v.count >= min_hits],
        key=lambda kv: (-kv[0][1].count("/"), -kv[1].count),
    )
    for (method, template), s in rows:
        prop_tmpl, groups, conf = _proposed(template, s.slot_roles)
        pattern = _tmpl_to_raw_pattern(prop_tmpl)
        lines += [
            f"# {method} {prop_tmpl}  —  {s.count} hits, confidence {conf:.2f}",
            "_add(",
            f'    r"{pattern}",',
            f'    "{prop_tmpl}",',
            f"    {groups!r},",
            ")",
            "",
        ]
    return "\n".join(lines)


def build_md(stats_map: dict[tuple[str, str], RouteStats], min_hits: int) -> str:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = sum(v.count for v in stats_map.values())
    rows = sorted(
        [(k, v) for k, v in stats_map.items() if v.count >= min_hits],
        key=lambda kv: -kv[1].count,
    )
    lines = [
        "# REST classification candidates\n",
        f"_Generated at {ts}. {total} events across {len(stats_map)} templates._\n",
        "| Hits | Status | Method | Proposed template | Confidence | Sample path |",
        "|---|---|---|---|---|---|",
    ]
    for (method, template), s in rows:
        prop_tmpl, _, conf = _proposed(template, s.slot_roles)
        lines.append(
            f"| {s.count} | {_status_mix(s.status_counts)} | {method}"
            f" | `{prop_tmpl}` | {conf:.2f} | `{s.sample_path}` |"
        )
    lines += ["", "## Sample response bodies", ""]
    for (method, template), s in rows:
        if s.sample_body:
            prop_tmpl, _, _ = _proposed(template, s.slot_roles)
            lines += [f"### {method} {prop_tmpl}\n", f"```json\n{s.sample_body}\n```\n"]
    return "\n".join(lines) + "\n"


async def _run(args: argparse.Namespace) -> None:
    stats_map: dict[tuple[str, str], RouteStats] = defaultdict(RouteStats)
    console = Console()

    async def on_msg(msg: nats.aio.msg.Msg) -> None:
        try:
            env = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        payload = env.get("payload")
        if not isinstance(payload, dict):
            return
        method = payload.get("method")
        template = payload.get("route_template")
        path = payload.get("path")
        status = payload.get("status")
        body = payload.get("body")
        if not (
            isinstance(method, str)
            and isinstance(template, str)
            and isinstance(path, str)
            and isinstance(status, int)
        ):
            return
        observe(stats_map[(method, template)], template, path, status, body)

    nc = await nats.connect(NATS_URL)
    await nc.subscribe(SUBJECT, cb=on_msg)
    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                live.update(build_table(stats_map, args.min_hits))
                await asyncio.sleep(REFRESH_INTERVAL)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        try:
            await nc.drain()
        except Exception:
            pass
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                build_py(stats_map, args.min_hits)
                if args.format == "py"
                else build_md(stats_map, args.min_hits)
            )
            output_path.write_text(content, encoding="utf-8")
            console.print(f"Saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", default=None, help="Write report to file on exit")
    parser.add_argument(
        "--format", choices=("md", "py"), default="md", help="Output format (default: md)"
    )
    parser.add_argument(
        "--min-hits",
        type=int,
        default=3,
        metavar="N",
        help="Minimum hits to show/output (default: 3)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
