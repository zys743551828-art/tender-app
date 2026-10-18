"""隔离本地识别进程：限时、续租检查、逐页输出与明确的待核验状态。"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bidwb.config import Settings
from bidwb.parsing import Chunk, ParsedDocument
from bidwb.util import xml_safe

MODEL_FILES = {
    "PP-OCRv6_det_small.onnx": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    "PP-OCRv6_rec_small.onnx": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
}
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class LocatedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    bbox: Annotated[list[Annotated[float, Field(ge=0, le=1)]], Field(min_length=4, max_length=4)]

    @field_validator("bbox")
    @classmethod
    def _valid_box(cls, value: list[float]) -> list[float]:
        if value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("invalid candidate bounds")
        return value


class CandidateLine(LocatedCandidate):
    text: Annotated[str, Field(max_length=20000)]
    confidence: Annotated[float, Field(ge=0, le=1)]


class CandidateTable(LocatedCandidate):
    rows: Annotated[list[Annotated[list[str | None], Field(max_length=100)]], Field(max_length=1000)]


class PageEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    physical_page: Annotated[int, Field(ge=1)]
    source_sha256: str
    ocr_status: Literal["not_needed", "recognized_pending", "empty", "failed", "unavailable", "limited"]
    table_status: Literal["extracted_pending", "none_detected", "failed", "limited"]
    lines: Annotated[list[CandidateLine], Field(max_length=2000)] = Field(default_factory=list)
    tables: Annotated[list[CandidateTable], Field(max_length=20)] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    render_sha256: str | None = None
    render_size: list[int] | None = None
    engines: dict[str, str] = Field(default_factory=dict)


def _reader(stream: Any, messages: queue.Queue[str | None]) -> None:
    try:
        while line := stream.readline(MAX_MESSAGE_BYTES + 1):
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                messages.put("invalid_message")
                return
            messages.put(line)
    finally:
        messages.put(None)


def _collect(
    process: subprocess.Popen[str],
    messages: queue.Queue[str | None],
    settings: Settings,
    checkpoint: Callable[[], None],
    result: dict[str, Any],
    started: float,
) -> set[int]:
    selected, source_sha = result["selected_pages"], result["source_sha256"]
    page_started = time.monotonic()
    seen: set[int] = set()
    while True:
        checkpoint()
        now = time.monotonic()
        if now - started > settings.parse_enrichment_total_seconds or now - page_started > settings.parse_enrichment_page_seconds:
            result["failure"] = "document_timeout" if now - started > settings.parse_enrichment_total_seconds else "page_timeout"
            break
        try:
            line = messages.get(timeout=0.25)
        except queue.Empty:
            continue
        if line is None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                result["failure"] = "worker_failed"
                break
            if process.returncode or len(seen) != len(selected):
                result["failure"] = "worker_failed"
            break
        try:
            payload = json.loads(line)
            if payload.get("event") == "page_started":
                if payload.get("physical_page") not in selected:
                    raise ValueError("unexpected page")
                page_started = now
                continue
            page = PageEnrichment.model_validate(payload)
            if page.source_sha256 != source_sha or page.physical_page not in selected or page.physical_page in seen:
                raise ValueError("source or page mismatch")
        except (ValueError, ValidationError, AttributeError):
            result["failure"] = "invalid_output"
            break
        seen.add(page.physical_page)
        result["pages"].append(page.model_dump())
        page_started = time.monotonic()
    return seen


def enrich_document(data: bytes, document: ParsedDocument, settings: Settings, checkpoint: Callable[[], None]) -> dict[str, Any]:
    """产物保留全部选择／跳过状态；子进程不持有数据库、对象存储或模型 API 凭据。"""
    source_sha = hashlib.sha256(data).hexdigest()
    ordered = sorted(document.pages, key=lambda p: (not bool(p.raster_images), p.text_chars >= 80, p.physical_page))
    selected = [p.physical_page for p in ordered[: settings.parse_enrichment_max_pages]]
    result: dict[str, Any] = {
        "schema": "local-enrichment-1",
        "source_sha256": source_sha,
        "selected_pages": selected,
        "skipped_pages": [p.physical_page for p in ordered[settings.parse_enrichment_max_pages :]],
        "pages": [],
        "failure": None,
        "review": "pending",
        "coordinate_space": "rendered_page_normalized",
        "render_scale": 2,
        "render_hash_scope": "RGB pixels",
        "model_files": MODEL_FILES,
        "unfinished_pages": selected,
    }
    messages: queue.Queue[str | None] = queue.Queue()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="bidwb-parse-") as directory:
        source = Path(directory) / "source.pdf"
        source.write_bytes(data)
        request = Path(directory) / "request.json"
        request.write_text(
            json.dumps(
                {
                    "source": str(source),
                    "source_sha256": source_sha,
                    "pages": selected,
                    "ocr_pages": [
                        p.physical_page for p in ordered if p.physical_page in selected and (p.raster_images or p.text_layer == "empty")
                    ],
                    "model_dir": settings.parse_model_dir,
                }
            ),
            encoding="utf-8",
        )
        # 仅继承运行本地 CPU 模型需要的系统变量；不把业务密钥带进识别进程。
        env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH"}}
        env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2", PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        command = [settings.parse_enrichment_python or sys.executable, "-m", "bidwb.enrichment_worker", str(request)]
        with (Path(directory) / "stderr.log").open("w", encoding="utf-8") as errors:
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8", env=env)  # noqa: S603
            except OSError:
                result["failure"] = "worker_unavailable"
                return result
            assert process.stdout is not None
            reader = threading.Thread(target=_reader, args=(process.stdout, messages), daemon=True)
            reader.start()
            try:
                seen = _collect(process, messages, settings, checkpoint, result, started)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                reader.join(timeout=2)
                process.stdout.close()
    result["unfinished_pages"] = [p for p in selected if p not in seen]
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


def candidate_chunks(enrichment: dict[str, Any]) -> list[Chunk]:
    """识别结果以待核验类型落库，不冒充原生文字，也不补造表头或跨页关系。"""
    candidates: list[Chunk] = []
    for raw in enrichment["pages"]:
        page = PageEnrichment.model_validate(raw)
        for line in page.lines:
            value = xml_safe(line.text).strip()
            for offset in range(0, len(value), 400):
                quote = value[offset : offset + 400]
                if quote:
                    candidates.append(
                        Chunk(
                            page.physical_page,
                            quote,
                            line.bbox,
                            "visual_observation",
                            "ocr",
                            line.confidence,
                            any(c.isdigit() or c in "%‰" for c in quote),
                        )
                    )
        for table in page.tables:
            for row in table.rows:
                value = " | ".join(xml_safe(c).strip() if c else "" for c in row).strip()
                for offset in range(0, len(value), 400):
                    quote = value[offset : offset + 400]
                    if quote:
                        candidates.append(
                            Chunk(
                                page.physical_page,
                                quote,
                                table.bbox,
                                "table",
                                "native_table",
                                None,
                                any(c.isdigit() or c in "%‰" for c in quote),
                            )
                        )
    return candidates
