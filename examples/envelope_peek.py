# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py", "rich"]
# ///
"""Wait for one event on a subject pattern and pretty-print its envelope.

Run:
    uv run --script examples/envelope_peek.py
    uv run --script examples/envelope_peek.py 'discord.gateway.message_create'
    uv run --script examples/envelope_peek.py 'discord.guild.*.channel.*.MESSAGE_CREATE'
"""

from __future__ import annotations

import asyncio
import json
import sys

import nats
from rich.console import Console
from rich.syntax import Syntax

NATS_URL = "nats://127.0.0.1:4333"
DEFAULT_SUBJECT = "discord.>"

console = Console()


async def main() -> None:
    subject = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SUBJECT
    console.print(f"[dim]waiting for one event on[/dim] [bold]{subject}[/bold][dim] ...[/dim]")

    nc = await nats.connect(NATS_URL)
    sub = await nc.subscribe(subject)
    try:
        msg = await sub.next_msg(timeout=None)
    finally:
        await sub.unsubscribe()
        await nc.drain()

    try:
        env = json.loads(msg.data)
        body = json.dumps(env, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        body = msg.data.decode("utf-8", errors="replace")

    console.print(f"[bold]subject:[/bold] {msg.subject}")
    console.print(Syntax(body, "json", theme="ansi_dark", word_wrap=True))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
