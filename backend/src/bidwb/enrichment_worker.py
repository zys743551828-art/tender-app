"""本地 CPU 识别子进程；stdout 只输出逐页 JSON，日志写 stderr。"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from bidwb.parse_enrichment import MODEL_FILES
from bidwb.table_candidates import raster_tables

MAX_RENDER_PIXELS = 12_000_000
MAX_OCR_LINES = 2000
MAX_TABLES = 20
MAX_ROWS = 1000
MAX_COLUMNS = 100


def _ocr(model_dir: str | None) -> Any:
    if not model_dir:
        raise ValueError("models_not_configured")
    root = Path(model_dir)
    for name, expected in MODEL_FILES.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("model_hash_mismatch")
    from rapidocr import RapidOCR  # noqa: PLC0415

    return RapidOCR(
        params={
            "Global.log_level": "error",
            "Global.model_root_dir": str(root),
            "Det.model_path": str(root / "PP-OCRv6_det_small.onnx"),
            "Rec.model_path": str(root / "PP-OCRv6_rec_small.onnx"),
            "Cls.model_path": str(root / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 2,
        }
    )


def _bbox(points: Any, width: float, height: float) -> list[float]:
    xs, ys = [float(p[0]) / width for p in points], [float(p[1]) / height for p in points]
    return [round(min(max(v, 0), 1), 6) for v in (min(xs), min(ys), max(xs), max(ys))]


def _read_ocr(pdf: pdfium.PdfDocument, number: int, engine: Any, output: dict[str, Any]) -> None:
    with contextlib.closing(pdf[number - 1]) as page:
        width, height = page.get_size()
        if width * height * 4 > MAX_RENDER_PIXELS:
            output.update(ocr_status="limited")
            output["issues"].append("render_pixels_limit")
            return
        with contextlib.closing(page.render(scale=2)) as bitmap:
            image = bitmap.to_pil().convert("RGB")
        output["render_sha256"] = hashlib.sha256(image.tobytes()).hexdigest()
        output["render_size"] = [image.width, image.height]
        recognized = engine(image)
        texts = recognized.txts or []
        output["ocr_status"] = "recognized_pending" if len(texts) else "empty"
        if len(texts) > MAX_OCR_LINES:
            output["ocr_status"] = "limited"
            output["issues"].append("ocr_lines_limit")
        for text, score, box in zip(
            texts[:MAX_OCR_LINES], recognized.scores or [], recognized.boxes if recognized.boxes is not None else [], strict=False
        ):
            if len(text) > 20000:
                output["ocr_status"] = "limited"
                output["issues"].append("ocr_line_length_limit")
                continue
            output["lines"].append({"text": text, "confidence": float(score), "bbox": _bbox(box, image.width, image.height)})
        try:
            detected = raster_tables(image, output["lines"])
        except Exception:
            output["issues"].append("raster_grid_failed")
            if not output["tables"]:
                output["table_status"] = "failed"
            return
        for table in detected:
            if any(max(abs(a - b) for a, b in zip(table["bbox"], old["bbox"], strict=True)) < 0.02 for old in output["tables"]):
                continue
            if len(output["tables"]) >= MAX_TABLES:
                output["issues"].append("tables_limit")
                break
            output["tables"].append(table)
        if any(table.get("source") == "raster_grid" for table in output["tables"]):
            output["table_status"] = "extracted_pending"


def _read_tables(pdf: Any, number: int, output: dict[str, Any]) -> None:
    page = pdf.pages[number - 1]
    tables = page.find_tables()
    output["table_status"] = "extracted_pending" if tables else "none_detected"
    if len(tables) > MAX_TABLES:
        output["table_status"] = "limited"
        output["issues"].append("tables_limit")
    for table in tables[:MAX_TABLES]:
        rows = table.extract()
        if len(rows) > MAX_ROWS or any(
            len(row) > MAX_COLUMNS or any(cell is not None and len(cell) > 20000 for cell in row) for row in rows
        ):
            output["table_status"] = "limited"
            output["issues"].append("table_cells_limit")
            continue
        x0, top, x1, bottom = table.bbox
        output["tables"].append(
            {
                "rows": rows,
                "bbox": _bbox([(x0, top), (x1, bottom)], page.width, page.height),
                "source": "native_table",
                "column_boundaries": sorted({round(v / page.width, 6) for cell in table.cells for v in (cell[0], cell[2])}),
                "row_boundaries": sorted({round(v / page.height, 6) for cell in table.cells for v in (cell[1], cell[3])}),
            }
        )
    page.close()


def _initialization_issue(exc: Exception) -> str:
    if isinstance(exc, ValueError) and str(exc) in {"models_not_configured", "model_hash_mismatch"}:
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return "models_missing"
    if isinstance(exc, ImportError):
        return "ocr_dependencies_unavailable"
    return "ocr_initialization_failed"


def run(request: dict[str, Any], emit: Any) -> None:
    import pdfplumber  # noqa: PLC0415

    source = Path(request["source"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != request["source_sha256"]:
        raise ValueError("source_hash_mismatch")
    engine = None
    engine_error = False
    engine_issue = "ocr_unavailable"
    versions = {name: importlib.metadata.version(name) for name in ("pdfplumber", "pypdfium2")}
    with pdfium.PdfDocument(source) as pdf, pdfplumber.open(source) as tables_pdf:
        for number in request["pages"]:
            emit({"event": "page_started", "physical_page": number})
            output: dict[str, Any] = {
                "physical_page": number,
                "source_sha256": request["source_sha256"],
                "ocr_status": "not_needed",
                "table_status": "none_detected",
                "lines": [],
                "tables": [],
                "issues": [],
                "engines": dict(versions),
            }
            try:
                _read_tables(tables_pdf, number, output)
            except Exception:
                output["table_status"] = "failed"
                output["issues"].append("table_read_failed")
            if number in request["ocr_pages"]:
                if engine is None and not engine_error:
                    try:
                        engine = _ocr(request["model_dir"])
                        versions.update({name: importlib.metadata.version(name) for name in ("rapidocr", "onnxruntime")})
                    except Exception as exc:
                        engine_error = True
                        engine_issue = _initialization_issue(exc)
                if engine is None:
                    output["ocr_status"] = "unavailable"
                    output["issues"].append(engine_issue)
                else:
                    try:
                        _read_ocr(pdf, number, engine, output)
                    except Exception:
                        output["ocr_status"] = "failed"
                        output["issues"].append("ocr_read_failed")
                output["engines"] = dict(versions)
            emit(output)


def main() -> None:
    output = sys.stdout
    sys.stdout = sys.stderr
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    def emit(value: dict[str, Any]) -> None:
        output.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        output.flush()

    with contextlib.redirect_stdout(sys.stderr):
        run(request, emit)


if __name__ == "__main__":
    main()
