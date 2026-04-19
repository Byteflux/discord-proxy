# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "rich"]
# ///
"""Colored firehose tail for discord-proxy.

Subscribes to `discord.>` and prints one line per event: timestamp, subject
(hash-colored by its top-level branch), and a compact payload summary,
truncated to the terminal width.

Run:
    uv run --script examples/firehose.py
"""

from __future__ import annotations

import asyncio
import json
import zlib
from datetime import datetime
from typing import Any

import nats
from rich.console import Console
from rich.text import Text

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.>"

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

console = Console()


def subject_color(subject: str) -> str:
    parts = subject.split(".", 2)
    key = parts[1] if len(parts) > 1 else subject
    return PALETTE[zlib.crc32(key.encode()) % len(PALETTE)]


def summarize(envelope: dict[str, Any]) -> str:
    bits = [str(envelope.get("event_type", "?"))]
    for k in ("guild_id", "channel_id", "user_id"):
        v = envelope.get(k)
        if v:
            bits.append(f"{k[0]}={v}")
    payload = envelope.get("payload") or {}
    content = payload.get("content") if isinstance(payload, dict) else None
    if isinstance(content, str) and content:
        bits.append(repr(content[:80]))
    return " ".join(bits)


async def main() -> None:
    nc = await nats.connect(NATS_URL)

    async def on_msg(msg: nats.aio.msg.Msg) -> None:
        try:
            env = json.loads(msg.data)
        except json.JSONDecodeError:
            env = {}
        ts = datetime.now().strftime("%H:%M:%S")
        line = Text.assemble(
            (f"{ts} ", "dim"),
            (msg.subject, subject_color(msg.subject)),
            "  ",
            summarize(env),
        )
        line.truncate(console.width, overflow="ellipsis")
        console.print(line)

    await nc.subscribe(SUBJECT, cb=on_msg)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await nc.drain()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
