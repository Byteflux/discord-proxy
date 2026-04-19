from typing import Any, Protocol, runtime_checkable

import erlpack
import zstandard


class UnsupportedCompression(Exception):
    pass


@runtime_checkable
class Decoder(Protocol):
    def feed(self, data: bytes) -> list[Any]: ...


class ZstdStreamDecoder:
    """Stateful decoder for a zstd-stream compressed gateway connection.

    Discord's desktop client negotiates compress=zstd-stream. Each WebSocket
    binary message contains exactly one complete zstd frame, but the
    decompressor maintains shared context across messages for better ratio.
    Allocate a fresh instance per WebSocket.
    """

    def __init__(self) -> None:
        dctx = zstandard.ZstdDecompressor(max_window_size=2**31)
        self._decomp = dctx.decompressobj()

    def feed(self, data: bytes) -> list[Any]:
        raw = self._decomp.decompress(data)
        return [erlpack.unpack(raw)]


def make_decoder(compression: str | None) -> Decoder:
    """Return the appropriate decoder for the given gateway compression type."""
    if compression == "zstd-stream":
        return ZstdStreamDecoder()
    raise UnsupportedCompression(compression)
