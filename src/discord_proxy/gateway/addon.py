import base64
import logging
from typing import Any

from mitmproxy import http

from discord_proxy.envelope import make_envelope
from discord_proxy.gateway.codec import Decoder, UnsupportedCompression, make_decoder
from discord_proxy.gateway.events import normalize
from discord_proxy.nats_client import NatsPublisher, dm_subject, flat_subject, scoped_subject

logger = logging.getLogger(__name__)


def _is_gateway(flow: http.HTTPFlow) -> bool:
    host = flow.request.pretty_host
    # Discord uses regional subdomains: gateway.discord.gg, gateway-us-east1-d.discord.gg, etc.
    return host.endswith(".discord.gg") and host.startswith("gateway")


class GatewayAddon:
    def __init__(self, publisher: NatsPublisher) -> None:
        self._pub = publisher
        self._decoders: dict[str, Decoder] = {}

    def websocket_start(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        if not _is_gateway(flow):
            logger.debug("Ignoring non-gateway websocket: %s", host)
            return
        compression = flow.request.query.get("compress")
        try:
            decoder = make_decoder(compression)
        except UnsupportedCompression:
            logger.warning(
                "Unsupported gateway compression %r on %s; skipping flow", compression, host
            )
            return
        self._decoders[flow.id] = decoder
        logger.info(
            "Gateway connection opened: host=%s compress=%s flow=%s", host, compression, flow.id
        )

    def websocket_end(self, flow: http.HTTPFlow) -> None:
        if self._decoders.pop(flow.id, None) is not None:
            logger.info("Gateway connection closed: %s", flow.id)

    def websocket_message(self, flow: http.HTTPFlow) -> None:
        if not _is_gateway(flow):
            return
        dec = self._decoders.get(flow.id)
        if dec is None:
            logger.warning(
                "No decoder for gateway flow %s (websocket_start may not have fired)", flow.id
            )
            return

        assert flow.websocket is not None
        msg = flow.websocket.messages[-1]
        if msg.from_client:
            # Client→server frames (heartbeat, identify, etc.) are not compressed ETF; skip.
            return
        data = msg.content

        try:
            payloads = dec.feed(data)
        except Exception:
            self._publish_decode_error(flow.id, data)
            return

        for decoded in payloads:
            try:
                envelope = normalize(decoded)
            except Exception:
                self._publish_decode_error(flow.id, data)
                continue
            if envelope is None:
                continue
            self._publish(envelope)

    def _publish(self, envelope: dict[str, Any]) -> None:
        event_type = envelope.get("event_type", "unknown")
        guild_id = envelope.get("guild_id")
        channel_id = envelope.get("channel_id")

        self._pub.publish(flat_subject(event_type), envelope)

        if guild_id and channel_id:
            self._pub.publish(scoped_subject(guild_id, channel_id, event_type), envelope)
        elif channel_id:
            self._pub.publish(dm_subject(channel_id, event_type), envelope)

    def _publish_decode_error(self, flow_id: str, raw: bytes) -> None:
        envelope = make_envelope(
            "gateway",
            "decode_error",
            {"flow_id": flow_id, "raw_b64": base64.b64encode(raw).decode()},
            {},
        )
        self._pub.publish("discord.meta.decode_error", envelope)
        logger.warning("Decode error on flow %s; published to discord.meta.decode_error", flow_id)
