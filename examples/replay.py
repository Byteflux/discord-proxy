# /// script
# requires-python = ">=3.12"
# dependencies = ["nats-py"]
# ///
"""Record and replay discord-proxy NATS traffic.

Record:
    uv run --script examples/replay.py record session.jsonl

Replay (stop the live proxy first, or use a different NATS server):
    uv run --script examples/replay.py play session.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import nats

NATS_URL = "nats://127.0.0.1:4333"
SUBJECT = "discord.>"


async def record(path: Path) -> None:
    nc = await nats.connect(NATS_URL)
    start: float | None = None
    count = 0

    with path.open("a", encoding="utf-8") as fh:

        async def on_msg(msg: nats.aio.msg.Msg) -> None:
            nonlocal start, count
            now = time.monotonic()
            if start is None:
                start = now
            try:
                envelope = json.loads(msg.data)
            except json.JSONDecodeError:
                envelope = {"_raw": msg.data.decode("utf-8", errors="replace")}
            fh.write(
                json.dumps(
                    {"t": now - start, "subject": msg.subject, "envelope": envelope},
                    ensure_ascii=False,
                )
                + "\n"
            )
            fh.flush()
            count += 1
            print(f"\rrecorded {count} events", end="", file=sys.stderr, flush=True)

        await nc.subscribe(SUBJECT, cb=on_msg)
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await nc.drain()
            print(file=sys.stderr)


async def play(path: Path) -> None:
    nc = await nats.connect(NATS_URL)
    playback_start = time.monotonic()
    count = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                entry = json.loads(raw)
                delay = playback_start + float(entry["t"]) - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                data = json.dumps(entry["envelope"], ensure_ascii=False).encode("utf-8")
                await nc.publish(entry["subject"], data)
                count += 1
                print(f"\rplayed {count} events", end="", file=sys.stderr, flush=True)
    finally:
        await nc.drain()
        print(file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record or replay discord-proxy NATS traffic.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="append live events to a JSONL file")
    rec.add_argument("file", type=Path)
    rep = sub.add_parser("play", help="replay events from a JSONL file with original timing")
    rep.add_argument("file", type=Path)
    args = parser.parse_args()

    try:
        if args.cmd == "record":
            asyncio.run(record(args.file))
        else:
            asyncio.run(play(args.file))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
