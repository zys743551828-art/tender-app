"""队列回执必须对应当前原件和方法；租约中止不留下可提交结果。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

from bidwb.word_conversion import ConversionUnavailable, _read, convert_word
from bidwb.workers.handlers import LeaseLost

FINGERPRINT = "a" * 64
ISOLATION = {"network": "none", "no_new_privileges": True, "capabilities": 0, "readonly_root": True, "landlock_abi": 6}


def queue(tmp_path: Path) -> tuple[Path, Path]:
    incoming, outgoing = tmp_path / "input", tmp_path / "output"
    incoming.mkdir()
    outgoing.mkdir()
    (outgoing / "renderer.json").write_text(json.dumps({"fingerprint": FINGERPRINT, "isolation": ISOLATION}))
    (outgoing / "heartbeat.json").write_text(json.dumps({"fingerprint": FINGERPRINT, "time": time.time()}))
    return incoming, outgoing


def respond(incoming: Path, outgoing: Path, changes: dict[str, Any] | None = None) -> None:
    for path in incoming.glob("*.request.json"):
        identity = path.name.removesuffix(".request.json")
        target = outgoing / f"{identity}.json"
        if target.exists():
            continue
        request = json.loads(path.read_text())
        pdf = b"%PDF-1.7 synthetic receipt digest fixture"
        report = {
            "contract": "word-conversion-1",
            "operation_id": identity,
            "source_sha256": request["source_sha256"],
            "renderer_fingerprint": FINGERPRINT,
            "isolation": ISOLATION,
            "state": "converted",
            "conversion_attempted": True,
            "page_count": 1,
            "pdf_bytes": len(pdf),
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "gaps": [],
            "inspection": {"container_validated": True, "conversion_eligible": True},
        }
        report.update(changes or {})
        (outgoing / f"{identity}.pdf").write_bytes(pdf)
        target.write_text(json.dumps(report))


@pytest.mark.parametrize(("state", "gaps"), [("converted", []), ("needs_review", ["complex_layout_requires_review"])])
def test_receives_pdf_and_cleans_only_own_request(tmp_path: Path, state: str, gaps: list[str]) -> None:
    incoming, outgoing = queue(tmp_path)
    sentinel = incoming / "other-operation.docx"
    sentinel.write_bytes(b"other original")
    result = convert_word(
        b"source",
        "外部改稿.docx",
        input_dir=incoming,
        output_dir=outgoing,
        renderer_fingerprint=FINGERPRINT,
        checkpoint=lambda: respond(incoming, outgoing, {"state": state, "gaps": gaps}),
    )
    assert result.pdf is not None and result.report["state"] == state
    assert list(incoming.iterdir()) == [sentinel]
    assert list(outgoing.glob("*.pdf")), "业务端不删除只读输出"


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": "b" * 32},
        {"source_sha256": "b" * 64},
        {"renderer_fingerprint": "b" * 64},
        {"isolation": {**ISOLATION, "network": "bridge"}},
        {"isolation": {**ISOLATION, "landlock_abi": 5}},
        {"pdf_sha256": "b" * 64},
        {"pdf_bytes": 1},
        {"page_count": True},
        {"page_count": 1001},
        {"state": "converted", "gaps": ["missing_text"]},
        {"conversion_attempted": False},
        {"inspection": {"container_validated": False, "conversion_eligible": True}},
    ],
)
def test_rejects_mismatched_or_inconsistent_receipt(tmp_path: Path, changes: dict[str, Any]) -> None:
    incoming, outgoing = queue(tmp_path)
    with pytest.raises(ConversionUnavailable):
        convert_word(
            b"source",
            "draft.docx",
            input_dir=incoming,
            output_dir=outgoing,
            renderer_fingerprint=FINGERPRINT,
            checkpoint=lambda: respond(incoming, outgoing, changes),
        )
    assert not list(incoming.iterdir())


def test_failure_does_not_adopt_any_pdf(tmp_path: Path) -> None:
    incoming, outgoing = queue(tmp_path)
    result = convert_word(
        b"source",
        "draft.docx",
        input_dir=incoming,
        output_dir=outgoing,
        renderer_fingerprint=FINGERPRINT,
        checkpoint=lambda: respond(
            incoming, outgoing, {"state": "failed", "error_code": "word_content_not_supported", "conversion_attempted": False}
        ),
    )
    assert result.pdf is None and result.report["conversion_attempted"] is False


def test_stale_renderer_does_not_publish_source(tmp_path: Path) -> None:
    incoming, outgoing = queue(tmp_path)
    (outgoing / "heartbeat.json").write_text(json.dumps({"fingerprint": FINGERPRINT, "time": time.time() - 130}))
    with pytest.raises(ConversionUnavailable, match="heartbeat_stale"):
        convert_word(
            b"source", "draft.docx", input_dir=incoming, output_dir=outgoing, renderer_fingerprint=FINGERPRINT, checkpoint=lambda: None
        )
    assert not list(incoming.iterdir())


def test_lease_cancellation_after_publication_cleans_request(tmp_path: Path) -> None:
    incoming, outgoing = queue(tmp_path)

    def checkpoint() -> None:
        if list(incoming.glob("*.request.json")):
            raise LeaseLost

    with pytest.raises(LeaseLost):
        convert_word(
            b"source", "draft.docx", input_dir=incoming, output_dir=outgoing, renderer_fingerprint=FINGERPRINT, checkpoint=checkpoint
        )
    assert not list(incoming.iterdir())


def test_timeout_cleans_original_and_request(tmp_path: Path) -> None:
    incoming, outgoing = queue(tmp_path)
    with pytest.raises(ConversionUnavailable, match="timeout"):
        convert_word(
            b"source",
            "draft.docx",
            input_dir=incoming,
            output_dir=outgoing,
            renderer_fingerprint=FINGERPRINT,
            checkpoint=lambda: None,
            timeout_seconds=0.001,
            poll_seconds=0.001,
        )
    assert not list(incoming.iterdir())


def test_queue_reader_rejects_oversize_and_nonregular(tmp_path: Path) -> None:
    target = tmp_path / "too-large"
    target.write_bytes(b"abcd")
    with pytest.raises(ConversionUnavailable, match="file_invalid"):
        _read(target, 3)
    with pytest.raises((ConversionUnavailable, OSError)):
        _read(tmp_path, 100)
