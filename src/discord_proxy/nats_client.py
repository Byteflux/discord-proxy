import asyncio
import json
import logging
from typing import Any

import nats
import nats.aio.client

logger = logging.getLogger(__name__)

_QUEUE_MAX = 1000


def flat_subject(event_type: str) -> str:
    return f"discord.gateway.{event_type.lower()}"


def scoped_subject(guild_id: str, channel_id: str, event_type: str) -> str:
    return f"discord.guild.{guild_id}.channel.{channel_id}.{event_type}"


def dm_subject(channel_id: str, event_type: str) -> str:
    return f"discord.dm.{channel_id}.{event_type}"


def rest_subject(method: str, route_template: str, *, classified: bool = True) -> str:
    # Replace path separators and braces so the subject is NATS-safe.
    token = route_template.strip("/").replace("/", ".").replace("{", "").replace("}", "")
    prefix = "discord.rest" if classified else "discord.rest.unclassified"
    return f"{prefix}.{method.upper()}.{token}"


class NatsPublisher:
    def __init__(self) -> None:
        self._nc: nats.aio.client.Client | None = None
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._task: asyncio.Task[None] | None = None
        self._dropped = 0

    async def connect(self, url: str) -> None:
        self._nc = await nats.connect(url)
        self._task = asyncio.create_task(self._worker(), name="nats-publisher")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._nc:
            await self._nc.drain()

    def publish(self, subject: str, envelope: dict[str, Any]) -> None:
        """Non-blocking enqueue. Drops and logs on queue overflow."""
        try:
            self._queue.put_nowait((subject, envelope))
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 100 == 0:
                logger.warning("NATS queue full; dropped %d events so far", self._dropped)

    async def _worker(self) -> None:
        while True:
            subject, envelope = await self._queue.get()
            try:
                if self._nc:
                    data = json.dumps(envelope, default=str).encode()
                    await self._nc.publish(subject, data)
            except Exception:
                logger.exception("Failed to publish to %s", subject)
            finally:
                self._queue.task_done()
