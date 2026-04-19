import json
import logging
import time
from typing import Any

from mitmproxy import http

from discord_proxy.envelope import make_envelope
from discord_proxy.nats_client import NatsPublisher, rest_subject
from discord_proxy.rest.routes import classify

logger = logging.getLogger(__name__)

_DISCORD_API_HOST_SUFFIX = "discord.com"
_API_PREFIX = "/api/"


def _is_discord_api(flow: http.HTTPFlow) -> bool:
    host = flow.request.pretty_host
    return host == _DISCORD_API_HOST_SUFFIX or host.endswith(f".{_DISCORD_API_HOST_SUFFIX}")


class RestAddon:
    def __init__(self, publisher: NatsPublisher) -> None:
        self._pub = publisher
        self._start_times: dict[str, float] = {}

    def request(self, flow: http.HTTPFlow) -> None:
        if not _is_discord_api(flow):
            return
        if not flow.request.path.startswith(_API_PREFIX):
            return
        self._start_times[flow.id] = time.monotonic()

    def response(self, flow: http.HTTPFlow) -> None:
        if not _is_discord_api(flow):
            return
        if not flow.request.path.startswith(_API_PREFIX):
            return
        if flow.response is None:
            return

        path, _, query = flow.request.path.partition("?")
        match = classify(path)
        if match is None:
            return

        elapsed_ms = None
        if (t0 := self._start_times.pop(flow.id, None)) is not None:
            elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

        body: Any = None
        ct = flow.response.headers.get("content-type", "")
        if "application/json" in ct and flow.response.content:
            try:
                body = json.loads(flow.response.content)
            except Exception:
                pass

        payload: dict[str, Any] = {
            "method": flow.request.method,
            "path": path,
            "query": query,
            "route_template": match.template,
            "ids": match.ids,
            "classified": match.classified,
            "status": flow.response.status_code,
            "elapsed_ms": elapsed_ms,
            "body": body,
        }

        guild_id = match.ids.get("guild_id")
        channel_id = match.ids.get("channel_id")
        user_id = match.ids.get("user_id")

        if isinstance(body, dict):
            if guild_id is None:
                guild_id = body.get("guild_id") or None
            if channel_id is None:
                channel_id = body.get("channel_id") or None
            if user_id is None:
                user_id = body.get("user_id") or None

        envelope = make_envelope(
            "rest",
            flow.request.method.upper(),
            payload,
            payload,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
        )

        subject = rest_subject(flow.request.method, match.template, classified=match.classified)
        self._pub.publish(subject, envelope)
