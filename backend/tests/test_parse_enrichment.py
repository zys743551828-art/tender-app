from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from bidwb import parse_enrichment
from bidwb.config import Settings
from bidwb.parsing import parse_pdf
from bidwb.workers.handlers import LeaseLost
from tests.pdfs import make_pdf


def _worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str) -> list[subprocess.Popen[str]]:
    script = tmp_path / "worker.py"
    script.write_text(
        "import json,sys,time,os\n"
        "request=json.load(open(sys.argv[1],encoding='utf-8'))\n"
        "assert 'BIDWB_LLM_API_KEY' not in os.environ\n"
        "page=request['pages'][0]\n"
        "print(json.dumps({'event':'page_started','physical_page':page}),flush=True)\n"
        "output={'physical_page':page,'source_sha256':request['source_sha256'],"
        "'ocr_status':'recognized_pending','table_status':'none_detected',"
        "'lines':[{'text':'费用15.12万元','confidence':0.98,'bbox':[0.1,0.2,0.8,0.3]}]}\n" + action + "\n",
        encoding="utf-8",
    )
    original = subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def start(command, **kwargs):  # type: ignore[no-untyped-def]
        child = original([sys.executable, str(script), command[-1]], **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(parse_enrichment.subprocess, "Popen", start)
    return processes


def test_recognition_is_pending_with_numeric_flag_and_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _worker(tmp_path, monkeypatch, "print(json.dumps(output),flush=True)")
    monkeypatch.setenv("BIDWB_LLM_API_KEY", "fixture-only")
    data = make_pdf([["扫描页码"], ["第二页"]], image_first=True)
    native = parse_pdf(data)
    result = parse_enrichment.enrich_document(data, native, Settings(parse_enrichment_max_pages=1), lambda: None)
    assert result["failure"] is None and result["unfinished_pages"] == []
    assert result["selected_pages"] == [1] and result["skipped_pages"] == [2]
    candidate = parse_enrichment.candidate_chunks(result)[0]
    assert candidate.kind == "visual_observation" and candidate.source == "ocr"
    assert candidate.numeric_review_required and candidate.confidence == 0.98
    assert "费用" not in native.chunks[0].quote


@pytest.mark.parametrize(
    "mutation", ["output['source_sha256']='wrong'", "output['physical_page']=99", "output['lines'][0]['confidence']=1.1"]
)
def test_wrong_source_page_or_confidence_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    _worker(tmp_path, monkeypatch, mutation + "\nprint(json.dumps(output),flush=True)")
    data = make_pdf([["正文"]])
    result = parse_enrichment.enrich_document(data, parse_pdf(data), Settings(), lambda: None)
    assert result["failure"] == "invalid_output" and result["pages"] == [] and result["unfinished_pages"] == [1]


def test_timeout_keeps_completed_pages_and_terminates_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processes = _worker(tmp_path, monkeypatch, "print(json.dumps(output),flush=True)\ntime.sleep(30)")
    data = make_pdf([["正文一"], ["正文二"]])
    result = parse_enrichment.enrich_document(data, parse_pdf(data), Settings(parse_enrichment_page_seconds=1), lambda: None)
    assert result["failure"] == "page_timeout" and len(result["pages"]) == 1
    assert result["unfinished_pages"] == [2] and processes[0].poll() is not None


def test_lease_loss_stops_child_and_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processes = _worker(tmp_path, monkeypatch, "time.sleep(30)")

    def checkpoint() -> None:
        raise LeaseLost

    data = make_pdf([["正文"]])
    with pytest.raises(LeaseLost):
        parse_enrichment.enrich_document(data, parse_pdf(data), Settings(), checkpoint)
    assert processes[0].poll() is not None


def test_missing_worker_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError

    monkeypatch.setattr(parse_enrichment.subprocess, "Popen", fail)
    data = make_pdf([["正文"]])
    result = parse_enrichment.enrich_document(data, parse_pdf(data), Settings(), lambda: None)
    assert result["failure"] == "worker_unavailable" and result["unfinished_pages"] == [1]


def test_bad_candidate_bbox_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_enrichment.CandidateLine(text="工期", confidence=0.99, bbox=[0.8, 0.3, 0.1, 0.4])


def test_table_rows_preserve_empty_cells_and_numeric_review() -> None:
    payload = {
        "pages": [
            {
                "physical_page": 2,
                "source_sha256": "fixture",
                "ocr_status": "not_needed",
                "table_status": "extracted_pending",
                "tables": [{"bbox": [0, 0, 1, 1], "rows": [["工人", None, "32"], ["另一项", "0", None]]}],
            }
        ]
    }
    rows = parse_enrichment.candidate_chunks(payload)
    assert rows[0].quote == "工人 |  | 32" and rows[0].kind == "table" and rows[0].source == "native_table"
    assert rows[0].numeric_review_required and rows[1].quote == "另一项 | 0 |"
