from typing import Any

import erlpack
import pytest
import zstandard
from zstandard import ZstdError

from discord_proxy.gateway.codec import (
    Decoder,
    UnsupportedCompression,
    ZstdStreamDecoder,
    make_decoder,
)


class _FakeZstdServer:
    """Simulates the Discord server's streaming zstd compressor for a connection."""

    def __init__(self) -> None:
        cctx = zstandard.ZstdCompressor()
        self._comp = cctx.compressobj()

    def frame(self, payload: dict[str, Any]) -> bytes:
        data = erlpack.pack(payload)
        return self._comp.compress(data) + self._comp.flush(zstandard.COMPRESSOBJ_FLUSH_BLOCK)


def _b(d: dict[str, Any]) -> dict[Any, Any]:
    """Convert a dict with str keys/values to bytes, as erlpack.pack produces."""
    out: dict[Any, Any] = {}
    for k, v in d.items():
        bk: Any = k.encode() if isinstance(k, str) else k
        bv: Any
        if isinstance(v, dict):
            bv = _b(v)
        elif isinstance(v, str):
            bv = v.encode()
        else:
            bv = v
        out[bk] = bv
    return out


class TestZstdStreamDecoder:
    def test_single_frame_roundtrip(self) -> None:
        payload = {"op": 0, "t": "MESSAGE_CREATE", "d": {"content": "hello"}}
        srv = _FakeZstdServer()
        dec = ZstdStreamDecoder()
        results = dec.feed(srv.frame(payload))
        assert results == [_b(payload)]

    def test_multi_frame(self) -> None:
        p1 = {"op": 0, "t": "A", "d": {}}
        p2 = {"op": 0, "t": "B", "d": {"x": 1}}
        srv = _FakeZstdServer()
        dec = ZstdStreamDecoder()
        r1 = dec.feed(srv.frame(p1))
        r2 = dec.feed(srv.frame(p2))
        assert r1 == [_b(p1)]
        assert r2 == [_b(p2)]

    def test_malformed_raises(self) -> None:
        dec = ZstdStreamDecoder()
        with pytest.raises(ZstdError):
            dec.feed(b"\xff\xff\xff\xff")

    def test_state_persists_across_feeds(self) -> None:
        payloads = [{"op": i, "d": {"seq": i}} for i in range(5)]
        srv = _FakeZstdServer()
        dec = ZstdStreamDecoder()
        for p in payloads:
            results = dec.feed(srv.frame(p))
            assert results == [_b(p)]


class TestMakeDecoder:
    def test_zstd_stream(self) -> None:
        assert isinstance(make_decoder("zstd-stream"), ZstdStreamDecoder)

    def test_none_raises(self) -> None:
        with pytest.raises(UnsupportedCompression):
            make_decoder(None)

    def test_unknown_raises(self) -> None:
        with pytest.raises(UnsupportedCompression):
            make_decoder("zlib-stream")

    def test_implements_decoder_protocol(self) -> None:
        assert isinstance(make_decoder("zstd-stream"), Decoder)
