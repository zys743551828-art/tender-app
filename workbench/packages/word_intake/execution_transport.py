"""Local test-only mailbox; no Docker, listener, credentials or rendering here.

The trusted host executor is a separate operator process. A timeout revokes this
request; it does not claim to interrupt conversion or confirm executor cleanup.
Binary slots are explicit and source/PDF qualification remains in the providers.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from packages.domain.errors import DomainError

PROTOCOL = "word-render-execution/1"
# Fixed Linux tmpfs private directory, checked for mount/owner/mode/nofollow below.
DIRECTORY = Path("/tmp/word-execution")  # nosec B108
ENVIRONMENT_KEY = "WORD_RENDER_EXECUTION_DIRECTORY"
MAX_REQUEST_BYTES = 160 * 1024 * 1024
MAX_RESPONSE_BYTES = 200 * 1024 * 1024
MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_MATERIAL_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BINARY_BYTES = 100 * 1024 * 1024
MAX_RESPONSE_BINARY_BYTES = 140 * 1024 * 1024
TIMEOUTS = {"external": 120, "page": 120, "rich": 240}
REQUEST_FILE = "request.json"
RESPONSE_FILE = "response.json"
CANCEL_FILE = "cancel"
_LOCK = threading.Lock()
_ID = re.compile(r"[0-9a-f]{32}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_ARGUMENTS = {
    "external": {"source", "profile"},
    "page": {"source", "snapshot", "producer_manifest", "profile"},
    "rich": {"snapshot", "materials", "profile", "mode"},
}
_RESULT_FIELDS = {
    "state",
    "coverage",
    "conversion_attempted",
    "error_code",
    "retryable",
    "gaps",
    "pdf",
    "docx",
    "protocol",
    "isolation",
    "measurements",
    "chain",
    "correspondence",
    "producer_manifest",
    "pagination",
    "render_iterations",
    "iteration_summaries",
    "navigation_proof",
    "navigation_history_proof",
    "adjustment_hint",
    "resource_receipt",
}


def _reject(code="WORD_EXECUTION_PROTOCOL_INVALID"):
    raise DomainError(code, "本机隔离转换运输不可用，请保留原件并重试", 503)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _reject()
        result[key] = value
    return result


def _plain(value, *, depth=0, budget=None):
    """Reject implicit Python coercion, nonfinite numbers and excessive structure."""
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 64 or budget[0] > 250_000:
        _reject("WORD_EXECUTION_LIMIT")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            _reject()
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            _reject()
        for item in value.values():
            _plain(item, depth=depth + 1, budget=budget)
        return
    if type(value) is list:
        for item in value:
            _plain(item, depth=depth + 1, budget=budget)
        return
    _reject()


def _loads(raw, limit):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        _reject("WORD_EXECUTION_LIMIT")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _reject(),
        )
        _plain(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        _reject()


def _dumps(value, limit):
    _plain(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (ValueError, UnicodeError, RecursionError):
        _reject()
    if len(raw) > limit:
        _reject("WORD_EXECUTION_LIMIT")
    return raw


def _binary(value, maximum, total, *, decode):
    if decode:
        if type(value) is not dict or set(value) != {"base64", "byte_size", "sha256"}:
            _reject()
        size, encoded, digest = value["byte_size"], value["base64"], value["sha256"]
        if type(size) is not int or not 0 < size <= maximum:
            _reject("WORD_EXECUTION_LIMIT")
        if type(encoded) is not str or len(encoded) != 4 * ((size + 2) // 3):
            _reject()
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            _reject()
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            _reject()
        if (
            len(raw) != size
            or _sha(raw) != digest
            or base64.b64encode(raw).decode("ascii") != encoded
        ):
            _reject()
    else:
        raw = value
        if type(raw) is not bytes or not 0 < len(raw) <= maximum:
            _reject("WORD_EXECUTION_LIMIT")
    total[0] += len(raw)
    if total[0] > total[1]:
        _reject("WORD_EXECUTION_LIMIT")
    if decode:
        return raw
    return {
        "base64": base64.b64encode(raw).decode("ascii"),
        "byte_size": len(raw),
        "sha256": _sha(raw),
    }


def _arguments(lane, arguments, *, decode):
    if type(lane) is not str or lane not in _ARGUMENTS or type(arguments) is not dict:
        _reject()
    if set(arguments) != _ARGUMENTS[lane]:
        _reject()
    value = dict(arguments)
    total = [0, MAX_REQUEST_BINARY_BYTES]
    if "source" in value:
        value["source"] = _binary(value["source"], MAX_SOURCE_BYTES, total, decode=decode)
    for key in ("profile", "snapshot", "producer_manifest"):
        if key in value and type(value[key]) is not dict:
            _reject()
    if lane == "rich":
        if type(value["mode"]) is not str or value["mode"] not in {
            "continuous",
            "chapter_start_new_page",
        }:
            _reject()
        if type(value["materials"]) is not list or len(value["materials"]) > 100:
            _reject("WORD_EXECUTION_LIMIT")
        materials = []
        keys = {"asset_id", "asset_revision", "asset_version_id", "bytes", "normalization_proof"}
        for item in value["materials"]:
            if type(item) is not dict or set(item) != keys:
                _reject()
            materials.append(
                item | {"bytes": _binary(item["bytes"], MAX_MATERIAL_BYTES, total, decode=decode)}
            )
        value["materials"] = materials
    # Binary objects have already been transformed; the rest must be plain JSON.
    check = (
        value
        if not decode
        else {k: v for k, v in value.items() if k not in {"source", "materials"}}
    )
    _plain(check)
    if decode and "materials" in value:
        _plain([{k: v for k, v in item.items() if k != "bytes"} for item in value["materials"]])
    return value


def _request(lane, arguments, request_id=None):
    identity = request_id or uuid4().hex
    if type(identity) is not str or _ID.fullmatch(identity) is None:
        _reject()
    return _dumps(
        {
            "protocol": PROTOCOL,
            "request_id": identity,
            "lane": lane,
            "arguments": _arguments(lane, arguments, decode=False),
        },
        MAX_REQUEST_BYTES,
    )


def decode_request(raw: bytes) -> dict:
    value = _loads(raw, MAX_REQUEST_BYTES)
    if type(value) is not dict or set(value) != {"protocol", "request_id", "lane", "arguments"}:
        _reject()
    if (
        value["protocol"] != PROTOCOL
        or type(value["request_id"]) is not str
        or _ID.fullmatch(value["request_id"]) is None
    ):
        _reject()
    return {
        "request_id": value["request_id"],
        "lane": value["lane"],
        "arguments": _arguments(value["lane"], value["arguments"], decode=True),
    }


def _result(result, *, decode):
    if type(result) is not dict or set(result) - _RESULT_FIELDS:
        _reject()
    required = {
        "state",
        "coverage",
        "conversion_attempted",
        "error_code",
        "retryable",
        "gaps",
        "chain",
        "pdf",
    }
    if not required <= set(result):
        _reject()
    if (
        result["state"] not in ("succeeded", "failed")
        or result["coverage"] not in ("complete", "partial", "failed")
        or type(result["conversion_attempted"]) is not bool
        or type(result["retryable"]) is not bool
        or type(result["gaps"]) is not list
        or any(type(gap) is not str for gap in result["gaps"])
        or type(result["chain"]) is not dict
        or (
            result["error_code"] is not None
            and (
                type(result["error_code"]) is not str
                or _CODE.fullmatch(result["error_code"]) is None
            )
        )
    ):
        _reject()
    value = dict(result)
    total = [0, MAX_RESPONSE_BINARY_BYTES]
    for key, maximum in (("pdf", MAX_PDF_BYTES), ("docx", MAX_SOURCE_BYTES)):
        if key in value and value[key] is not None:
            value[key] = _binary(value[key], maximum, total, decode=decode)
    if "render_iterations" in value:
        if type(value["render_iterations"]) is not list or len(value["render_iterations"]) > 3:
            _reject()
        iterations = []
        for item in value["render_iterations"]:
            if type(item) is not dict or set(item) != {"pdf_bytes", "docx_bytes", "entries"}:
                _reject()
            iterations.append(
                item
                | {
                    "pdf_bytes": _binary(item["pdf_bytes"], MAX_PDF_BYTES, total, decode=decode),
                    "docx_bytes": _binary(
                        item["docx_bytes"], MAX_SOURCE_BYTES, total, decode=decode
                    ),
                }
            )
        value["render_iterations"] = iterations
    if decode:
        _plain({k: v for k, v in value.items() if k not in {"pdf", "docx", "render_iterations"}})
        _plain([item["entries"] for item in value.get("render_iterations", [])])
    else:
        _plain(value)
    return value


def _response(request_raw, *, result=None, code=None):
    request = decode_request(request_raw)
    if code is not None and (type(code) is not str or _CODE.fullmatch(code) is None):
        _reject()
    return _dumps(
        {
            "protocol": PROTOCOL,
            "request_id": request["request_id"],
            "lane": request["lane"],
            "request_sha256": _sha(request_raw),
            "result": result,
            "error_code": code,
        },
        MAX_RESPONSE_BYTES,
    )


def encode_response(request_raw: bytes, result: dict) -> bytes:
    return _response(request_raw, result=_result(result, decode=False))


def encode_error(request_raw: bytes, code: str) -> bytes:
    return _response(request_raw, code=code)


def decode_response(request_raw: bytes, response_raw: bytes) -> dict:
    request = decode_request(request_raw)
    value = _loads(response_raw, MAX_RESPONSE_BYTES)
    if type(value) is not dict or set(value) != {
        "protocol",
        "request_id",
        "lane",
        "request_sha256",
        "result",
        "error_code",
    }:
        _reject()
    if (
        value["protocol"] != PROTOCOL
        or value["request_id"] != request["request_id"]
        or value["lane"] != request["lane"]
        or value["request_sha256"] != _sha(request_raw)
    ):
        _reject("WORD_EXECUTION_RESPONSE_MISMATCH")
    if value["error_code"] is not None:
        code = value["error_code"]
        if value["result"] is not None or type(code) is not str or _CODE.fullmatch(code) is None:
            _reject()
        _reject(code)
    return _result(value["result"], decode=True)


def enabled() -> bool:
    configured = os.environ.get(ENVIRONMENT_KEY)
    if configured is None:
        return False
    if not sys.platform.startswith("linux") or configured != str(DIRECTORY):
        _reject("WORD_EXECUTION_DIRECTORY_INVALID")
    return True


def _private(info, *, directory=False):
    if (
        info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        _reject("WORD_EXECUTION_FILE_INVALID")


def _tmpfs(path):
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if not separator or len(fields) < 5:
            continue
        mount = re.sub(r"\\([0-7]{3})", lambda item: chr(int(item[1], 8)), fields[4])
        if str(path) == mount or str(path).startswith(mount.rstrip("/") + "/"):
            mounts.append((len(mount), after.split()[0]))
    if not mounts or max(mounts)[1] != "tmpfs":
        _reject("WORD_EXECUTION_TMPFS_REQUIRED")


def _open_directory():
    _tmpfs(DIRECTORY)
    # Open the actual parent, then all children relative to that pinned fd.
    parent = os.open(DIRECTORY.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir(DIRECTORY.name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        descriptor = os.open(
            DIRECTORY.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
        )
        try:
            _private(os.fstat(descriptor), directory=True)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    finally:
        os.close(parent)


def _read(directory, name, maximum):
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        _private(before)
        if before.st_size > maximum:
            _reject("WORD_EXECUTION_LIMIT")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or len(raw) > maximum
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        ):
            _reject("WORD_EXECUTION_FILE_CHANGED")
        _private(after)
        return raw
    finally:
        os.close(descriptor)


def _publish(directory, name, raw):
    temporary = "." + name + "-" + uuid4().hex
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
        _private(os.fstat(descriptor))
        # Each final name has one fixed writer. Rename publishes a single-link
        # file atomically; a hard-link publication would expose nlink=2 briefly.
        try:
            os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            raise FileExistsError
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _cancel(directory):
    try:
        _publish(directory, CANCEL_FILE, b"")
    except FileExistsError:
        _read(directory, CANCEL_FILE, 0)


def call(lane: str, **arguments) -> dict:
    if not enabled():
        _reject("WORD_EXECUTION_NOT_CONFIGURED")
    request_raw = _request(lane, arguments)
    identity = decode_request(request_raw)["request_id"]
    timeout = TIMEOUTS[lane]
    deadline = time.monotonic() + timeout
    if not _LOCK.acquire(timeout=timeout):
        _reject("WORD_EXECUTION_TIMEOUT")
    root = job = lock = None
    try:
        root = _open_directory()
        # A second process must not consume the same tmpfs budget concurrently.
        import fcntl

        lock = os.open(
            ".client.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=root,
        )
        _private(os.fstat(lock))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _reject("WORD_EXECUTION_BUSY")
        capacity = os.fstatvfs(root)
        if (
            capacity.f_bavail * capacity.f_frsize
            < len(request_raw) + MAX_RESPONSE_BYTES + 8 * 1024 * 1024
        ):
            _reject("WORD_EXECUTION_LIMIT")
        os.mkdir(identity, mode=0o700, dir_fd=root)
        job = os.open(identity, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        _private(os.fstat(job), directory=True)
        _publish(job, REQUEST_FILE, request_raw)
        while True:
            if time.monotonic() >= deadline:
                _reject("WORD_EXECUTION_TIMEOUT")
            if _read(job, CANCEL_FILE, 0) is not None:
                _reject("WORD_EXECUTION_CANCELLED")
            response = _read(job, RESPONSE_FILE, MAX_RESPONSE_BYTES)
            if response is not None:
                if time.monotonic() >= deadline:
                    _reject("WORD_EXECUTION_TIMEOUT")
                result = decode_response(request_raw, response)
                if time.monotonic() >= deadline:
                    _reject("WORD_EXECUTION_TIMEOUT")
                os.unlink(RESPONSE_FILE, dir_fd=job)
                os.unlink(REQUEST_FILE, dir_fd=job)
                os.rmdir(identity, dir_fd=root)
                return result
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    except BaseException as error:
        if job is not None:
            try:
                _cancel(job)
            except (OSError, DomainError):
                if not isinstance(error, (KeyboardInterrupt, SystemExit)):
                    _reject("WORD_EXECUTION_CANCEL_UNCONFIRMED")
        if isinstance(error, OSError):
            _reject("WORD_EXECUTION_FILE_INVALID")
        raise
    finally:
        for descriptor in (job, lock, root):
            if descriptor is not None:
                os.close(descriptor)
        _LOCK.release()
