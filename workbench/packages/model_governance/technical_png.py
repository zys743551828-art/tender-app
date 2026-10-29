"""Bounded RGB8/filter-0 PNG codec for immutable page assets, without Pillow."""

import binascii
import hashlib
import struct
import zlib
from typing import NoReturn

MAX_DIMENSION = 8192
MAX_PIXELS = 24_000_000
MAX_BYTES = 32 * 1024 * 1024
SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PageAssetError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code: str) -> NoReturn:
    raise PageAssetError(code)


def dimensions(width, height):
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= MAX_DIMENSION
        or not 1 <= height <= MAX_DIMENSION
        or width * height > MAX_PIXELS
    ):
        fail("PAGE_ASSET_PIXEL_LIMIT")


def _chunk(kind, data):
    return (
        struct.pack("!I", len(data))
        + kind
        + data
        + struct.pack("!I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )


def encode_rgb(width, height, rows, *, limit=MAX_BYTES):
    dimensions(width, height)
    if type(limit) is not int or not 0 < limit <= MAX_BYTES:
        fail("PAGE_ASSET_BYTE_LIMIT")
    compressor = zlib.compressobj(level=6)
    pieces: list[bytes] = []
    total, count = 0, 0
    for row in rows:
        count += 1
        if count > height or not isinstance(row, (bytes, bytearray, memoryview)):
            fail("PAGE_ASSET_RGB_INVALID")
        packed = bytes(row)
        if len(packed) != width * 3:
            fail("PAGE_ASSET_RGB_INVALID")
        part = compressor.compress(b"\x00" + packed)
        total += len(part)
        if total + 57 > limit:
            fail("PAGE_ASSET_BYTE_LIMIT")
        pieces.append(part)
    if count != height:
        fail("PAGE_ASSET_RGB_INVALID")
    tail = compressor.flush()
    if total + len(tail) + 57 > limit:
        fail("PAGE_ASSET_BYTE_LIMIT")
    png = SIGNATURE + _chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
    return png + _chunk(b"IDAT", b"".join(pieces) + tail) + _chunk(b"IEND", b"")


def _payload(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES or not data.startswith(SIGNATURE):
        fail("PAGE_ASSET_PNG_INVALID")
    offset = len(SIGNATURE)
    payload: dict[bytes, bytes] = {}
    for expected in (b"IHDR", b"IDAT", b"IEND"):
        if offset + 12 > len(data):
            fail("PAGE_ASSET_PNG_INVALID")
        size = struct.unpack("!I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 8 + size
        if kind != expected or end + 4 > len(data):
            fail("PAGE_ASSET_PNG_INVALID")
        part = data[offset + 8 : end]
        if struct.unpack("!I", data[end : end + 4])[0] != binascii.crc32(kind + part) & 0xFFFFFFFF:
            fail("PAGE_ASSET_PNG_INVALID")
        payload[kind] = part
        offset = end + 4
    if offset != len(data) or len(payload[b"IHDR"]) != 13 or payload[b"IEND"]:
        fail("PAGE_ASSET_PNG_INVALID")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        "!IIBBBBB", payload[b"IHDR"]
    )
    dimensions(width, height)
    if (depth, color, compression, filtering, interlace) != (8, 2, 0, 0, 0):
        fail("PAGE_ASSET_PNG_FORMAT_UNSUPPORTED")
    return width, height, payload[b"IDAT"]


def png_size(data):
    width, height, _ = _payload(data)
    return width, height


def decode_rgb(data):
    width, height, compressed = _payload(data)
    expected_size = (width * 3 + 1) * height
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, expected_size + 1)
    except zlib.error:
        fail("PAGE_ASSET_PNG_INVALID")
    if (
        len(raw) != expected_size
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        fail("PAGE_ASSET_PNG_INVALID")
    stride = width * 3 + 1
    rows = []
    for row in range(height):
        start = row * stride
        if raw[start] != 0:
            fail("PAGE_ASSET_PNG_FORMAT_UNSUPPORTED")
        rows.append(raw[start + 1 : start + stride])
    return width, height, b"".join(rows)


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()
