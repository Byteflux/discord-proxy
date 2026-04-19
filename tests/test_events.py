from typing import Any

import erlpack

from discord_proxy.gateway.events import normalize

A = erlpack.Atom


def _etf(d: dict[str, Any]) -> dict[Any, Any]:
    """Simulate erlpack output for real Discord ETF: atom keys, atom/bytes values."""
    out: dict[Any, Any] = {}
    for k, v in d.items():
        ak: Any = A(k) if isinstance(k, str) else k
        av: Any
        if isinstance(v, dict):
            av = _etf(v)
        elif isinstance(v, str):
            av = A(v)
        elif isinstance(v, list):
            av = [_etf(i) if isinstance(i, dict) else i for i in v]
        else:
            av = v
        out[ak] = av
    return out


def _dispatch(t: str, d: dict[str, Any]) -> dict[Any, Any]:
    return _etf({"op": 0, "t": t, "s": 1, "d": d})


class TestNormalize:
    def test_non_dispatch_returns_none(self) -> None:
        assert normalize(_etf({"op": 10, "d": {"heartbeat_interval": 41250}})) is None

    def test_op0_no_t_returns_none(self) -> None:
        assert normalize(_etf({"op": 0, "d": {}})) is None

    def test_message_create(self) -> None:
        raw_d = {
            "id": "111",
            "channel_id": "222",
            "guild_id": "333",
            "content": "hello",
            "author": {"id": "444", "username": "user"},
        }
        result = normalize(_dispatch("MESSAGE_CREATE", raw_d))
        assert result is not None
        assert result["event_type"] == "MESSAGE_CREATE"
        assert result["source"] == "gateway"
        assert result["guild_id"] == "333"
        assert result["channel_id"] == "222"
        assert result["user_id"] == "444"
        assert result["payload"]["content"] == "hello"
        assert "raw" in result
        assert "captured_at" in result

    def test_message_delete(self) -> None:
        raw_d = {"id": "111", "channel_id": "222", "guild_id": "333"}
        result = normalize(_dispatch("MESSAGE_DELETE", raw_d))
        assert result is not None
        assert result["event_type"] == "MESSAGE_DELETE"
        assert result["guild_id"] == "333"
        assert result["channel_id"] == "222"
        assert result["user_id"] is None

    def test_dm_message_has_no_guild(self) -> None:
        raw_d = {
            "id": "111",
            "channel_id": "222",
            "content": "dm",
            "author": {"id": "444", "username": "user"},
        }
        result = normalize(_dispatch("MESSAGE_CREATE", raw_d))
        assert result is not None
        assert result["guild_id"] is None
        assert result["channel_id"] == "222"

    def test_typing_start(self) -> None:
        raw_d = {"channel_id": "222", "guild_id": "333", "user_id": "444"}
        result = normalize(_dispatch("TYPING_START", raw_d))
        assert result is not None
        assert result["event_type"] == "TYPING_START"
        assert result["user_id"] == "444"

    def test_presence_update(self) -> None:
        raw_d = {"guild_id": "333", "user": {"id": "444"}, "status": "online"}
        result = normalize(_dispatch("PRESENCE_UPDATE", raw_d))
        assert result is not None
        assert result["event_type"] == "PRESENCE_UPDATE"
        assert result["user_id"] == "444"

    def test_ready_strips_guilds(self) -> None:
        raw_d = {
            "v": 10,
            "user": {"id": "999", "username": "me"},
            "session_id": "abc",
            "guilds": [{"id": "1"}, {"id": "2"}],
            "users": [{"id": "3"}],
        }
        result = normalize(_dispatch("READY", raw_d))
        assert result is not None
        assert result["user_id"] == "999"
        assert "guilds" not in result["payload"]
        assert "users" not in result["payload"]
        assert "guilds" in result["raw"]["d"]

    def test_unknown_event_passes_through(self) -> None:
        raw_d = {"foo": "bar"}
        result = normalize(_dispatch("SOME_UNKNOWN_EVENT", raw_d))
        assert result is not None
        assert result["event_type"] == "SOME_UNKNOWN_EVENT"
        assert result["payload"] == {"foo": "bar"}
