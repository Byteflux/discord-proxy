# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "textual"]
# ///
"""Live rate meter for discord-proxy event types.

Subscribes to `discord.>` and displays a scrollable table with events/sec
(last 10s), events/min (last 60s), total count, and a sparkline of the
last 30 seconds. Rows are sorted by current /sec descending.

Run:
    uv run --script examples/rate_meter.py
"""

from __future__ import annotations

import json
import time
import zlib
from collections import defaultdict, deque
from typing import ClassVar

import nats
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.>"
REFRESH_INTERVAL = 0.5
WINDOW_SEC = 60
SPARK_SEC = 30
SPARK_CHARS = " ▁▂▃▄▅▆▇█"

PALETTE = [
    "bright_red",
    "bright_green",
    "bright_yellow",
    "bright_blue",
    "bright_magenta",
    "bright_cyan",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
]


def color_for_etype(etype: str) -> str:
    return PALETTE[zlib.crc32(etype.encode()) % len(PALETTE)]


def style_rate(r: float) -> Text:
    s = f"{r:.1f}"
    if r == 0:
        return Text(s, style="dim")
    if r < 1:
        return Text(s)
    if r < 5:
        return Text(s, style="green")
    return Text(s, style="bold yellow")


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

    def sparkline(self, now: float) -> str:
        buckets = [0] * SPARK_SEC
        start = now - SPARK_SEC
        for t in self.stamps:
            if t >= start:
                buckets[min(SPARK_SEC - 1, int(t - start))] += 1
        peak = max(buckets) or 1
        step = len(SPARK_CHARS) - 1
        return "".join(SPARK_CHARS[min(step, b * step // peak)] for b in buckets)


class RateMeterApp(App[None]):
    TITLE = "discord-proxy · event rates"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]
    CSS = "DataTable { height: 1fr; }"

    def __init__(self) -> None:
        super().__init__()
        self.counters: dict[str, Counter] = defaultdict(Counter)
        self.ordered_etypes: list[str] = []
        self.nc: nats.NATS | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(zebra_stripes=True)
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("event_type", "total", "/sec", "/min", f"last {SPARK_SEC}s")
        table.cursor_type = "row"
        self.nc = await nats.connect(NATS_URL)
        await self.nc.subscribe(SUBJECT, cb=self._on_msg)
        self.set_interval(REFRESH_INTERVAL, self._refresh)

    async def _on_msg(self, msg: nats.aio.msg.Msg) -> None:
        try:
            etype = json.loads(msg.data).get("event_type")
        except json.JSONDecodeError:
            return
        if isinstance(etype, str):
            self.counters[etype].add(time.monotonic())

    def _refresh(self) -> None:
        now = time.monotonic()
        rows = []
        for etype, c in self.counters.items():
            c.trim(now)
            rows.append((etype, c.total, c.per_sec(now), c.per_min(), c.sparkline(now)))
        rows.sort(key=lambda r: r[2], reverse=True)

        table = self.query_one(DataTable)
        selected_etype: str | None = None
        if 0 <= table.cursor_row < len(self.ordered_etypes):
            selected_etype = self.ordered_etypes[table.cursor_row]

        table.clear()
        self.ordered_etypes = [r[0] for r in rows]
        for etype, total, ps, pm, spark in rows:
            color = color_for_etype(etype)
            table.add_row(
                Text(etype, style=f"bold {color}"),
                Text(f"{total}", style="dim"),
                style_rate(ps),
                f"{pm}",
                Text(spark, style="bright_cyan"),
            )

        if selected_etype is not None and selected_etype in self.ordered_etypes:
            table.move_cursor(row=self.ordered_etypes.index(selected_etype))

    async def on_unmount(self) -> None:
        if self.nc is not None:
            await self.nc.drain()


if __name__ == "__main__":
    RateMeterApp().run()
