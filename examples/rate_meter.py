# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "textual"]
# ///
"""Live subject-tree rate meter for discord-proxy.

Subscribes to `discord.>` and renders observed subjects as a scrollable
tree. Every node (leaf and branch) shows events/sec (last 10s), events/min
(last 60s), total count, and a sparkline of the last 30 seconds, rolled up
from its descendants. Guild IDs and channel IDs are replaced with human-
readable names once a GUILD_CREATE / CHANNEL_CREATE payload is seen.

Run:
    uv run --script examples/rate_meter.py
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from typing import Any, ClassVar

import nats
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.>"
REFRESH_INTERVAL = 0.5
WINDOW_SEC = 60
SPARK_SEC = 30
SPARK_CHARS = " ▁▂▃▄▅▆▇█"

BRANCH_COLORS = {
    "gateway": "bright_cyan",
    "guild": "bright_magenta",
    "dm": "bright_green",
    "rest": "bright_blue",
    "meta": "bright_red",
}

REST_METHOD_COLORS = {
    "GET": "green",
    "POST": "yellow",
    "PUT": "blue",
    "PATCH": "blue",
    "DELETE": "red",
}


def rate_markup(r: float) -> str:
    s = f"{r:.1f}"
    if r == 0:
        return f"[dim]{s}[/dim]"
    if r < 1:
        return s
    if r < 5:
        return f"[green]{s}[/green]"
    return f"[bold yellow]{s}[/bold yellow]"


def sparkline_from_buckets(bkts: list[int]) -> str:
    peak = max(bkts) or 1
    step = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[min(step, b * step // peak)] for b in bkts)


def style_token(
    token: str,
    position: int,
    parts: list[str],
    guild_names: dict[str, str],
    channel_names: dict[str, str],
) -> str:
    if position == 1 and token in BRANCH_COLORS:
        return f"[bold {BRANCH_COLORS[token]}]{token}[/]"
    if position == 2 and parts[0] == "guild":
        name = guild_names.get(token)
        if name:
            return f"[bold bright_magenta]{name}[/]  [dim]{token}[/dim]"
    if position == 4 and parts[0] == "guild" and len(parts) >= 3 and parts[2] == "channel":
        name = channel_names.get(token)
        if name:
            return f"[bold]#{name}[/]  [dim]{token}[/dim]"
    if position == 2 and parts[0] == "dm":
        name = channel_names.get(token)
        if name:
            return f"[bold bright_green]@{name}[/]  [dim]{token}[/dim]"
    if position == 2 and parts[0] == "rest" and token in REST_METHOD_COLORS:
        return f"[bold {REST_METHOD_COLORS[token]}]{token}[/]"
    if token.isdigit() and len(token) >= 17:
        return f"[dim]{token}[/dim]"
    if token.isupper() and "_" in token:
        return f"[bold yellow]{token}[/]"
    return token


class Counter:
    __slots__ = ("stamps", "total")

    def __init__(self) -> None:
        self.total = 0
        self.stamps: deque[float] = deque()

    def add(self, now: float) -> None:
        self.total += 1
        self.stamps.append(now)

    def trim(self, now: float) -> None:
        cutoff = now - WINDOW_SEC
        while self.stamps and self.stamps[0] < cutoff:
            self.stamps.popleft()

    def per_sec(self, now: float) -> float:
        return sum(1 for t in self.stamps if t >= now - 10) / 10.0

    def per_min(self) -> int:
        return len(self.stamps)

    def buckets(self, now: float) -> list[int]:
        result = [0] * SPARK_SEC
        start = now - SPARK_SEC
        for t in self.stamps:
            if t >= start:
                result[min(SPARK_SEC - 1, int(t - start))] += 1
        return result


class RateMeterApp(App[None]):
    TITLE = "discord-proxy · subject rate tree"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]
    CSS = "Tree { height: 1fr; }"

    def __init__(self) -> None:
        super().__init__()
        self.counters: dict[str, Counter] = defaultdict(Counter)
        self.subjects: set[str] = set()
        self.nodes: dict[tuple[str, ...], TreeNode[None]] = {}
        self.guild_names: dict[str, str] = {}
        self.channel_names: dict[str, str] = {}
        self.nc: nats.NATS | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Tree("discord.>", id="subjects")
        yield Footer()

    async def on_mount(self) -> None:
        tree: Tree[None] = self.query_one(Tree)
        tree.root.expand()
        self.nodes[()] = tree.root
        self.nc = await nats.connect(NATS_URL)
        await self.nc.subscribe(SUBJECT, cb=self._on_msg)
        self.set_interval(REFRESH_INTERVAL, self._refresh)

    async def _on_msg(self, msg: nats.aio.msg.Msg) -> None:
        self.subjects.add(msg.subject)
        self.counters[msg.subject].add(time.monotonic())
        try:
            env = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if isinstance(env, dict):
            self._learn(env)

    def _learn(self, env: dict[str, Any]) -> None:
        if env.get("source") == "rest":
            self._learn_rest(env.get("payload") or {})
            return
        etype = env.get("event_type")
        if etype == "READY":
            raw = env.get("raw")
            d = raw.get("d") if isinstance(raw, dict) else None
            if isinstance(d, dict):
                for g in d.get("guilds") or []:
                    if isinstance(g, dict):
                        self._record_guild(g)
            return
        data = env.get("payload") or {}
        if not isinstance(data, dict):
            return
        if etype in ("GUILD_CREATE", "GUILD_UPDATE"):
            self._record_guild(data)
        elif etype in ("CHANNEL_CREATE", "CHANNEL_UPDATE", "THREAD_CREATE", "THREAD_UPDATE"):
            self._record_channel(data)

    def _learn_rest(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or payload.get("status") != 200:
            return
        template = payload.get("route_template")
        body = payload.get("body")
        if template == "/guilds/{guild_id}" and isinstance(body, dict):
            self._record_guild(body)
        elif template == "/channels/{channel_id}" and isinstance(body, dict):
            self._record_channel(body)
        elif template == "/guilds/{guild_id}/channels" and isinstance(body, list):
            for c in body:
                if isinstance(c, dict):
                    self._record_channel(c)
        elif template == "/users/@me/guilds" and isinstance(body, list):
            for g in body:
                if isinstance(g, dict):
                    self._record_guild(g)

    def _record_guild(self, g: dict[str, Any]) -> None:
        gid = str(g.get("id") or "")
        gname = g.get("name")
        if not gname:
            props = g.get("properties")
            if isinstance(props, dict):
                gname = props.get("name")
        if gid and isinstance(gname, str) and gname:
            self.guild_names[gid] = gname
        for ch in (g.get("channels") or []) + (g.get("threads") or []):
            if isinstance(ch, dict):
                self._record_channel(ch)

    def _record_channel(self, ch: dict[str, Any]) -> None:
        cid = str(ch.get("id") or "")
        cname = ch.get("name")
        if cid and isinstance(cname, str) and cname:
            self.channel_names[cid] = cname

    def _node_label(self, styled: str, ps: float, pm: int, total: int, bkts: list[int]) -> str:
        spark = sparkline_from_buckets(bkts)
        return (
            f"{styled}  "
            f"[dim]/s[/dim] {rate_markup(ps)}  "
            f"[dim]/m[/dim] {pm}  "
            f"[dim]∑[/dim] {total}  "
            f"[bright_cyan]{spark}[/bright_cyan]"
        )

    def _refresh(self) -> None:
        now = time.monotonic()
        for c in self.counters.values():
            c.trim(now)

        agg_total: dict[tuple[str, ...], int] = defaultdict(int)
        agg_ps: dict[tuple[str, ...], float] = defaultdict(float)
        agg_pm: dict[tuple[str, ...], int] = defaultdict(int)
        agg_bkts: dict[tuple[str, ...], list[int]] = {}

        for subject in self.subjects:
            c = self.counters[subject]
            leaf_bkts = c.buckets(now)
            parts = subject.removeprefix("discord.").split(".")
            for i in range(len(parts) + 1):  # 0 = root aggregate
                key: tuple[str, ...] = tuple(parts[:i])
                agg_total[key] += c.total
                agg_ps[key] += c.per_sec(now)
                agg_pm[key] += c.per_min()
                if key not in agg_bkts:
                    agg_bkts[key] = [0] * SPARK_SEC
                for j in range(SPARK_SEC):
                    agg_bkts[key][j] += leaf_bkts[j]

        tree: Tree[None] = self.query_one(Tree)
        root_bkts = agg_bkts.get((), [0] * SPARK_SEC)
        spark = sparkline_from_buckets(root_bkts)
        tree.root.label = (
            f"[bold]discord.>[/bold]  "
            f"[dim]/s[/dim] {rate_markup(agg_ps.get((), 0.0))}  "
            f"[dim]/m[/dim] {agg_pm.get((), 0)}  "
            f"[dim]∑[/dim] {agg_total.get((), 0)}  "
            f"[bright_cyan]{spark}[/bright_cyan]"
        )

        for subject in sorted(self.subjects):
            parts = subject.removeprefix("discord.").split(".")
            for i in range(1, len(parts) + 1):
                key = tuple(parts[:i])
                styled = style_token(parts[i - 1], i, parts, self.guild_names, self.channel_names)
                label = self._node_label(
                    styled,
                    agg_ps.get(key, 0.0),
                    agg_pm.get(key, 0),
                    agg_total.get(key, 0),
                    agg_bkts.get(key, [0] * SPARK_SEC),
                )
                if key in self.nodes:
                    self.nodes[key].label = label
                else:
                    self.nodes[key] = self.nodes[key[:-1]].add(label, expand=True)

    async def on_unmount(self) -> None:
        if self.nc is not None:
            await self.nc.drain()


if __name__ == "__main__":
    RateMeterApp().run()
