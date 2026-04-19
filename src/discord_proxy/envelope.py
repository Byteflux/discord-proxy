from datetime import UTC, datetime
from typing import Any, Literal


def make_envelope(
    source: Literal["gateway", "rest"],
    event_type: str,
    payload: dict[str, Any],
    raw: dict[str, Any],
    *,
    guild_id: str | None = None,
    channel_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "source": source,
        "event_type": event_type,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "payload": payload,
        "raw": raw,
    }
