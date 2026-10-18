"""业务 worker 的受限队列客户端；仅交付已核对身份的回执和 PDF 字节。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SOURCE = 100 * 1024 * 1024
MAX_PDF = 50 * 1024 * 1024
MAX_REPORT = 2 * 1024 * 1024
MIN_LANDLOCK_ABI = 6


class ConversionUnavailable(Exception):
    """转换运行时或回执不可用；原件保留，业务侧提供逐文件 PDF 补交。"""


@dataclass(frozen=True)
class ConversionResult:
    report: dict[str, Any]
    pdf: bytes | None


def _read(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= limit:
            raise ConversionUnavailable("word_queue_file_invalid")
        data = stream.read(limit + 1)
    if len(data) != metadata.st_size:
        raise ConversionUnavailable("word_queue_size_changed")
    return data


def _json(path: Path, limit: int = MAX_REPORT) -> dict[str, Any]:
    value = json.loads(_read(path, limit))
    if not isinstance(value, dict):
        raise ConversionUnavailable("word_queue_json_invalid")
    return value


def _isolated(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("network") == "none"
        and value.get("no_new_privileges") is True
        and value.get("readonly_root") is True
        and type(value.get("capabilities")) is int
        and value["capabilities"] == 0
        and type(value.get("landlock_abi")) is int
        and value["landlock_abi"] >= MIN_LANDLOCK_ABI
    )


def _ready(output: Path, expected: str) -> None:
    renderer = _json(output / "renderer.json", 8192)
    heartbeat = _json(output / "heartbeat.json", 8192)
    if renderer.get("fingerprint") != expected or heartbeat.get("fingerprint") != expected or not _isolated(renderer.get("isolation")):
        raise ConversionUnavailable("word_renderer_mismatch")
    timestamp = heartbeat.get("time")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int | float) or not -5 <= time.time() - timestamp < 120:
        raise ConversionUnavailable("word_renderer_heartbeat_stale")


def _publish(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _receive(output: Path, identity: str, expected: str, source_sha: str) -> ConversionResult:
    report = _json(output / f"{identity}.json")
    if (
        report.get("operation_id") != identity
        or report.get("source_sha256") != source_sha
        or report.get("renderer_fingerprint") != expected
        or report.get("contract") != "word-conversion-1"
        or not _isolated(report.get("isolation"))
        or type(report.get("conversion_attempted")) is not bool
    ):
        raise ConversionUnavailable("word_receipt_identity_invalid")
    state = report.get("state")
    if state == "failed" and isinstance(report.get("error_code"), str):
        return ConversionResult(report, None)
    if state not in {"converted", "needs_review"} or report["conversion_attempted"] is not True:
        raise ConversionUnavailable("word_receipt_state_invalid")
    gaps = report.get("gaps")
    inspection = report.get("inspection")
    if (
        not isinstance(gaps, list)
        or not all(isinstance(gap, str) for gap in gaps)
        or bool(gaps) != (state == "needs_review")
        or not isinstance(inspection, dict)
        or inspection.get("container_validated") is not True
        or inspection.get("conversion_eligible") is not True
    ):
        raise ConversionUnavailable("word_receipt_checks_invalid")
    pages = report.get("page_count")
    if type(pages) is not int or not 0 < pages <= 1000:
        raise ConversionUnavailable("word_receipt_pages_invalid")
    data = _read(output / f"{identity}.pdf", MAX_PDF)
    if (
        not data.startswith(b"%PDF-")
        or len(data) != report.get("pdf_bytes")
        or hashlib.sha256(data).hexdigest() != report.get("pdf_sha256")
    ):
        raise ConversionUnavailable("word_pdf_digest_invalid")
    return ConversionResult(report, data)


def convert_word(
    data: bytes,
    filename: str,
    *,
    input_dir: Path,
    output_dir: Path,
    renderer_fingerprint: str,
    checkpoint: Callable[[], None],
    timeout_seconds: float = 100,
    poll_seconds: float = 0.25,
) -> ConversionResult:
    """等待中保持租约检查；只删除本次输入，不修改输出和其他操作文件。"""
    if not re.fullmatch(r"[0-9a-f]{64}", renderer_fingerprint) or not 0 < len(data) <= MAX_SOURCE:
        raise ConversionUnavailable("word_conversion_input_invalid")
    if not 0 < timeout_seconds <= 120 or not 0 <= poll_seconds <= 1:
        raise ConversionUnavailable("word_conversion_wait_invalid")
    identity = uuid.uuid4().hex
    source_sha = hashlib.sha256(data).hexdigest()
    source_path = input_dir / f"{identity}.docx"
    request_path = input_dir / f"{identity}.request.json"
    temporary = input_dir / f"{identity}.request.tmp"
    owned: list[Path] = []
    try:
        checkpoint()
        _ready(output_dir, renderer_fingerprint)
        request = json.dumps(
            {"filename": filename, "source_sha256": source_sha, "source_bytes": len(data), "renderer_fingerprint": renderer_fingerprint},
            ensure_ascii=False,
        ).encode()
        if len(request) > 8192:
            raise ConversionUnavailable("word_request_too_large")
        _publish(source_path, data)
        owned.append(source_path)
        _publish(temporary, request)
        owned.append(temporary)
        temporary.replace(request_path)
        owned.append(request_path)
        deadline = time.monotonic() + timeout_seconds
        while True:
            checkpoint()
            if (output_dir / f"{identity}.json").exists():
                result = _receive(output_dir, identity, renderer_fingerprint, source_sha)
                checkpoint()
                return result
            if time.monotonic() >= deadline:
                raise ConversionUnavailable("word_conversion_timeout")
            time.sleep(poll_seconds)
    except (OSError, ValueError, TypeError) as error:
        raise ConversionUnavailable("word_conversion_queue_unavailable") from error
    finally:
        # 先撤销请求再移除原件，避免取消后仍被队列拾取。
        for path in reversed(owned):
            with suppress(OSError):
                path.unlink(missing_ok=True)
