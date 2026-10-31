"""Worker compute-phase adapter: no document bytes or tokens reach an HTTP proxy."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 100 * 1024 * 1024


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


class ParsingUnavailable(Exception):
    pass


def runtime_token():
    mode = os.environ.get("PARSING_RUNTIME_TRANSPORT", "loopback")
    if mode == "loopback" and not os.environ.get("PARSING_RUNTIME_TOKEN_FILE"):
        return os.environ.get("PARSING_RUNTIME_TOKEN", "")
    if (
        mode != "compose-private"
        or not sys.platform.startswith("linux")
        or os.environ.get("PARSING_RUNTIME_TOKEN_FILE") != "/parser-private/token"
        or os.environ.get("PARSING_RUNTIME_TOKEN")
    ):
        raise ParsingUnavailable("PARSING_RUNTIME_TOKEN_CONFIG_INVALID")
    descriptor = None
    try:
        directory = os.stat("/parser-private", follow_symlinks=False)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 65532
            or directory.st_gid != 65532
            or stat.S_IMODE(directory.st_mode) != 0o700
        ):
            raise ValueError()
        descriptor = os.open("/parser-private/token", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != 65532
            or info.st_gid != 65532
            or info.st_nlink != 1
            or not 32 <= info.st_size <= 256
        ):
            raise ValueError()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(257)
        after = os.fstat(descriptor)
        if len(raw) != info.st_size or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError()
        token = raw.decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
            raise ValueError()
        return token
    except (OSError, UnicodeError, ValueError):
        raise ParsingUnavailable("PARSING_RUNTIME_TOKEN_FILE_INVALID") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


class ParsingHttp:
    def __init__(self):
        raw_url = os.environ.get("PARSING_RUNTIME_URL", "http://127.0.0.1:8812")
        mode = os.environ.get("PARSING_RUNTIME_TRANSPORT", "loopback")
        self.url = raw_url.rstrip("/")
        target = urlsplit(self.url)
        if (
            target.scheme != "http"
            or not (
                (mode == "loopback" and target.hostname == "127.0.0.1")
                or (mode == "compose-private" and raw_url == "http://parser:8812")
            )
            or target.path
            or target.username
            or target.query
            or target.fragment
        ):
            raise ParsingUnavailable("PARSING_RUNTIME_CONFIG_INVALID")
        self.token = runtime_token()
        if len(self.token) < 32:
            raise ParsingUnavailable("PARSING_RUNTIME_NOT_CONFIGURED")
        metadata = self._call("GET", "/identity")
        if metadata.get("protocol_version") != 1:
            raise ParsingUnavailable("PARSING_RUNTIME_PROTOCOL_MISMATCH")
        self.parser_digest = metadata["parser_digest"]
        self.config_digest = metadata["config_digest"]
        self.identity = metadata["identity"]
        if digest(self.identity) != self.parser_digest or not re.fullmatch(
            r"[0-9a-f]{64}", self.config_digest
        ):
            raise ParsingUnavailable("PARSING_RUNTIME_IDENTITY_MISMATCH")

    def _call(self, method, path, data=None):
        headers = {"Authorization": "Bearer " + self.token}
        if data is not None:
            headers.update({"Content-Type": "application/pdf", "X-Source-Sha256": digest(data)})
        try:
            with httpx.Client(
                timeout=httpx.Timeout(600, connect=3), trust_env=False, follow_redirects=False
            ) as client:
                response = client.request(method, self.url + path, content=data, headers=headers)
            if response.status_code != 200:
                raise ParsingUnavailable("PARSING_RUNTIME_REJECTED")
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ParsingUnavailable("PARSING_RUNTIME_UNAVAILABLE") from error

    def parse(self, data: bytes):
        if not 0 < len(data) <= MAX_BYTES:
            raise ParsingUnavailable("PARSING_INPUT_TOO_LARGE")
        result = self._call("POST", "/parse", data)
        if (
            result.get("source_digest") != digest(data)
            or result.get("parser_digest") != self.parser_digest
            or result.get("config_digest") != self.config_digest
        ):
            raise ParsingUnavailable("PARSING_RESULT_IDENTITY_MISMATCH")
        if result.get("page_count") != len(result.get("pages", [])) or result.get(
            "coverage"
        ) not in {"usable", "partial", "failed"}:
            raise ParsingUnavailable("PARSING_RESULT_INVALID")
        try:
            for ordinal, page in enumerate(result["pages"], start=1):
                width, height = page["width"], page["height"]
                if (
                    page["physical_page"] != ordinal
                    or min(width, height) <= 0
                    or not math.isfinite(width * height)
                    or page["rotation"] not in {0, 90, 180, 270}
                ):
                    raise ValueError("page")
                if result["coverage"] == "usable" and (page["gaps"] or page["quality"] != "usable"):
                    raise ValueError("coverage")
                for position, block in enumerate(page["blocks"]):
                    if (
                        block["ordinal"] != position
                        or block["physical_page"] != ordinal
                        or digest(block["text_content"].encode()) != block["digest"]
                    ):
                        raise ValueError("evidence")
                    area = block["bbox"]
                    if area is not None and (
                        len(area) != 4
                        or not all(math.isfinite(x) for x in area)
                        or not 0 <= area[0] < area[2] <= width
                        or not 0 <= area[1] < area[3] <= height
                    ):
                        raise ValueError("bbox")
        except (KeyError, TypeError, ValueError) as error:
            raise ParsingUnavailable("PARSING_RESULT_INVALID") from error
        return result
