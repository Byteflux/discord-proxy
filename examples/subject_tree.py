# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "textual"]
# ///
"""Live subject-tree viewer for discord-proxy.

Subscribes to `discord.>` on NATS and renders observed subjects as a
scrollable tree with per-subject event counts. Learns guild and channel
names from GUILD_CREATE / CHANNEL_CREATE payloads so snowflakes in the
tree get human-readable labels as events arrive. Scroll with arrow keys,
mouse wheel, or PgUp/PgDn. Press `q` to quit.

Run:
    uv run --script examples/subject_tree.py
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
REFRESH_INTERVAL = 0.5

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


class SubjectTreeApp(App[None]):
    TITLE = "discord-proxy · subject tree"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]
    CSS = "Tree { height: 1fr; }"

    def __init__(self) -> None:
        super().__init__()
        self.counts: dict[str, int] = defaultdict(int)
        self.nodes: dict[tuple[str, ...], TreeNode] = {}
        self.guild_names: dict[str, str] = {}
        self.channel_names: dict[str, str] = {}
        self.nc: nats.NATS | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Tree("discord.>", id="subjects")
        yield Footer()

    async def on_mount(self) -> None:
        tree = self.query_one(Tree)
        tree.root.expand()
        self.nodes[()] = tree.root
        self.nc = await nats.connect(NATS_URL)
        await self.nc.subscribe(SUBJECT, cb=self._on_msg)
        self.set_interval(REFRESH_INTERVAL, self._refresh)

    async def _on_msg(self, msg: nats.aio.msg.Msg) -> None:
        self.counts[msg.subject] += 1
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

    def _refresh(self) -> None:
        tree = self.query_one(Tree)
        total = sum(self.counts.values())
        tree.root.label = f"[bold]discord.>[/bold]  [dim]({total} events)[/dim]"
        for subject in sorted(self.counts):
            parts = subject.removeprefix("discord.").split(".")
            for i in range(1, len(parts) + 1):
                key = tuple(parts[:i])
                styled = style_token(parts[i - 1], i, parts, self.guild_names, self.channel_names)
                label = (
                    f"{styled}  [dim]({self.counts[subject]})[/dim]" if i == len(parts) else styled
                )
                if key in self.nodes:
                    self.nodes[key].label = label
                else:
                    self.nodes[key] = self.nodes[key[:-1]].add(label, expand=True)

    async def on_unmount(self) -> None:
        if self.nc is not None:
            await self.nc.drain()


if __name__ == "__main__":
    SubjectTreeApp().run()
