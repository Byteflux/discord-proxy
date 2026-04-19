from typing import Any

import erlpack

from discord_proxy.envelope import make_envelope


def _decode(val: Any) -> Any:
    """Recursively convert erlpack output to Python-native types.

    ETF atoms arrive as erlpack.Atom (a str subclass). Booleans are atoms
    true/false; null is atom nil. ETF binaries arrive as bytes.
    """
    if isinstance(val, erlpack.Atom):
        s = str(val)
        if s == "true":
            return True
        if s == "false":
            return False
        if s == "nil":
            return None
        return s
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8")
        except UnicodeDecodeError:
            return val
    if isinstance(val, dict):
        return {_decode(k): _decode(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_decode(i) for i in val]
    return val


def normalize(decoded: dict[Any, Any]) -> dict[str, Any] | None:
    """Normalize a raw erlpack-decoded gateway payload into an envelope.

    Discord sends ETF with atom keys (erlpack.Atom, a str subclass).
    All key lookups use str; both Atom("op") and "op" resolve correctly.

    Returns None for non-dispatch ops and event types excluded from publishing.
    """
    op = decoded.get("op")
    if op != 0:
        return None

    t = decoded.get("t")
    if not t:
        return None

    event_type = str(t)
    d: dict[Any, Any] = decoded.get("d") or {}
    raw = _decode(decoded)

    if event_type == "READY":
        return _normalize_ready(event_type, d, raw)
    if event_type in ("MESSAGE_CREATE", "MESSAGE_UPDATE"):
        return _normalize_message(event_type, d, raw)
    if event_type == "MESSAGE_DELETE":
        return _normalize_message_delete(event_type, d, raw)
    if event_type == "TYPING_START":
        return _normalize_typing_start(event_type, d, raw)
    if event_type == "PRESENCE_UPDATE":
        return _normalize_presence_update(event_type, d, raw)

    nd = _decode(d)
    return make_envelope("gateway", event_type, nd, raw)


def _normalize_ready(event_type: str, d: dict[Any, Any], raw: dict[str, Any]) -> dict[str, Any]:
    nd = _decode(d)
    payload = {k: v for k, v in nd.items() if k not in ("guilds", "users", "merged_members")}
    user = nd.get("user") or {}
    return make_envelope("gateway", event_type, payload, raw, user_id=user.get("id"))


def _normalize_message(event_type: str, d: dict[Any, Any], raw: dict[str, Any]) -> dict[str, Any]:
    nd = _decode(d)
    author = nd.get("author") or {}
    return make_envelope(
        "gateway",
        event_type,
        nd,
        raw,
        guild_id=nd.get("guild_id"),
        channel_id=nd.get("channel_id"),
        user_id=author.get("id"),
    )


def _normalize_message_delete(
    event_type: str, d: dict[Any, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    nd = _decode(d)
    return make_envelope(
        "gateway",
        event_type,
        nd,
        raw,
        guild_id=nd.get("guild_id"),
        channel_id=nd.get("channel_id"),
    )


def _normalize_typing_start(
    event_type: str, d: dict[Any, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    nd = _decode(d)
    return make_envelope(
        "gateway",
        event_type,
        nd,
        raw,
        guild_id=nd.get("guild_id"),
        channel_id=nd.get("channel_id"),
        user_id=nd.get("user_id"),
    )


def _normalize_presence_update(
    event_type: str, d: dict[Any, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    nd = _decode(d)
    user = nd.get("user") or {}
    return make_envelope(
        "gateway",
        event_type,
        nd,
        raw,
        guild_id=nd.get("guild_id"),
        user_id=user.get("id"),
    )
