"""业务 Word／PDF 身份、补交、晚到结果及历史输入；转换质量另由真实容器实验验证。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from bidwb import db, tasks
from bidwb.messaging import InMemoryBus
from bidwb.services import current_materials
from bidwb.word_conversion import ConversionResult
from bidwb.workers import word_handler
from bidwb.workers.handlers import default_handlers
from bidwb.workers.runner import WorkerRunner
from tests.pdfs import make_pdf
from tests.test_files_and_parse import _setup, _upload
from tests.test_product_logic import _flow, _ready
from tests.test_word_inspection import make_word

pytestmark = pytest.mark.integration
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF = make_pdf([["施工组织设计", "施工工期180日历天，做好安全文明施工。"]])


def setup(api_factory: Any, make_member: Any, worker_container: Any, engine: Any) -> tuple[Any, str, WorkerRunner]:
    api, pid = _setup(api_factory, make_member)
    bus = InMemoryBus()
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="word-business-test")
    return api, pid, runner


def drain(runner: WorkerRunner, engine: Any) -> None:
    for _ in range(20):
        with engine.begin() as conn:
            job = db.scalar(conn, "SELECT id FROM jobs WHERE kind='parse' AND state='queued' ORDER BY created_at,id LIMIT 1")
            if job is None:
                return
            claim = tasks.claim_job(conn, job, "word-test", "parse", 60)
        assert claim is not None
        runner.execute(claim)
    raise AssertionError("parse jobs did not finish")


def word(api: Any, store: Any, pid: str, text: str = "正文第一版", version_of: str | None = None) -> dict[str, Any]:
    response = _upload(api, store, pid, make_word(text), name="施组.docx", role="body", media=DOCX, version_of=version_of)[1]
    assert response.status_code == 200, response.text
    return response.json()


def configure(monkeypatch: Any, runner: WorkerRunner, state: str = "converted", during: Any = None) -> None:
    runner.ctr.settings.word_input_dir = Path("unused-input")
    runner.ctr.settings.word_output_dir = Path("unused-output")
    runner.ctr.settings.word_renderer_fingerprint = "a" * 64

    def convert(*args: Any, **kwargs: Any) -> ConversionResult:
        if during:
            during()
        return ConversionResult(
            {
                "state": state,
                "gaps": ["complex_layout_requires_review"] if state == "needs_review" else [],
                "renderer_fingerprint": "a" * 64,
            },
            PDF,
        )

    monkeypatch.setattr(word_handler, "convert_word", convert)


def test_unavailable_renderer_retains_original_and_failed_receipt(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    api, pid, runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    drain(runner, engine)
    listed = api.get(f"/projects/{pid}/files").json()
    assert len(listed) == 1 and listed[0]["version_id"] == original["version_id"]
    assert listed[0]["word"]["state"] == "failed" and listed[0]["word"]["error_code"] == "word_renderer_not_configured"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM word_conversions WHERE state='failed'") == 1
        assert db.scalar(conn, "SELECT count(*) FROM parses") == 0
        assert current_materials.active_body(conn, pid) == original["version_id"]


def test_one_file_pdf_fallback_and_new_word_excludes_old_pdf(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    api, pid, runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    drain(runner, engine)
    pdf = _upload(api, store, pid, PDF, role="body", name="施组.pdf", source_word=original["version_id"])[1].json()
    assert pdf["file_id"] != original["file_id"] and pdf["supersedes"] is None and pdf["source_word_version_id"] == original["version_id"]
    locked = api.post(
        f"/projects/{pid}/uploads",
        {
            "original_name": "改.pdf",
            "role": "body",
            "byte_size": 1,
            "sha256": "a" * 64,
            "media_type": "application/pdf",
            "version_of_file_id": pdf["file_id"],
        },
    )
    assert locked.status_code == 422 and locked.json()["code"] == "word_pdf_version_locked"
    drain(runner, engine)
    with engine.connect() as conn:
        assert current_materials.active_body(conn, pid) == pdf["version_id"]
        assert current_materials.lineage(conn, pid, [pdf["version_id"]])[0]["method"] == "user_declared"
    updated = word(api, store, pid, "正文第二版", original["file_id"])
    with engine.connect() as conn:
        assert current_materials.active_body(conn, pid) == updated["version_id"]
    old = next(r for r in api.get(f"/projects/{pid}/files").json() if r["version_id"] == original["version_id"])
    assert old["word"]["current"] is False and old["word"]["adopted_pdf_version_id"] == pdf["version_id"]
    link = old["word"]["candidates"][0]["link_id"]
    response = api.post(f"/files/{original['version_id']}/word:adopt", {"link_id": link, "reason": "旧稿", "reviewed_pdf": True})
    assert response.status_code == 409 and response.json()["code"] == "word_source_stale"


def test_late_conversion_cannot_replace_new_word(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any, monkeypatch: Any
) -> None:
    api, pid, runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    updated: list[dict[str, Any]] = []
    configure(monkeypatch, runner, during=lambda: updated.append(word(api, store, pid, "改稿第二版", original["file_id"])))
    with engine.begin() as conn:
        job = db.scalar(conn, "SELECT id FROM jobs WHERE kind='parse' LIMIT 1")
        claim = tasks.claim_job(conn, job, "word-test", "parse", 60)
    assert claim is not None
    runner.execute(claim)
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM word_pdf_links") == 1
        assert db.scalar(conn, "SELECT count(*) FROM word_pdf_adoptions") == 0
        assert current_materials.active_body(conn, pid) == updated[0]["version_id"]


def test_late_conversion_keeps_user_adopted_pdf(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any, monkeypatch: Any
) -> None:
    api, pid, runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    manual: list[dict[str, Any]] = []
    configure(
        monkeypatch,
        runner,
        during=lambda: manual.append(_upload(api, store, pid, PDF, role="body", source_word=original["version_id"])[1].json()),
    )
    drain(runner, engine)
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM word_pdf_links") == 2
        assert current_materials.active_body(conn, pid) == manual[0]["version_id"]


def test_complex_pdf_requires_explicit_review_before_adoption(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any, monkeypatch: Any
) -> None:
    api, pid, runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    configure(monkeypatch, runner, "needs_review")
    drain(runner, engine)
    entry = next(r for r in api.get(f"/projects/{pid}/files").json() if r["version_id"] == original["version_id"])
    assert entry["word"]["state"] == "needs_review" and entry["word"]["adopted_pdf_version_id"] is None
    candidate = entry["word"]["candidates"][0]
    body = {"link_id": candidate["link_id"], "reason": "已逐页核对表格和字体", "reviewed_pdf": False}
    assert api.post(f"/files/{original['version_id']}/word:adopt", body).status_code == 422
    body["reviewed_pdf"] = True
    assert api.post(f"/files/{original['version_id']}/word:adopt", body).status_code == 200
    with engine.connect() as conn:
        assert current_materials.active_body(conn, pid) == candidate["pdf_version_id"]


def test_word_and_pdf_cannot_share_version_chain(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    api, pid, _ = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    response = api.post(
        f"/projects/{pid}/uploads",
        {
            "original_name": "施组.pdf",
            "role": "body",
            "byte_size": 1,
            "sha256": "a" * 64,
            "media_type": "application/pdf",
            "version_of_file_id": original["file_id"],
        },
    )
    assert response.status_code == 422 and response.json()["code"] == "version_media_family_mismatch"


def test_snapshot_keeps_word_and_actual_pdf_lineage(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any, monkeypatch: Any
) -> None:
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    original = word(flow.api, store, flow.pid)
    configure(monkeypatch, flow.parse_runner)
    flow.drain()
    drain(flow.parse_runner, engine)
    with engine.connect() as conn:
        flow.body = current_materials.active_body(conn, flow.pid)
    snapshot = flow.freeze(rules)
    assert snapshot.status_code == 200, snapshot.text
    frozen = snapshot.json()
    assert frozen["word_sources"][0]["source_version_id"] == original["version_id"]
    assert frozen["word_sources"][0]["pdf_version_id"] == flow.body
    assert original["version_id"] not in frozen["file_version_ids"]
    word(flow.api, store, flow.pid, "新的正文原稿", original["file_id"])
    assert flow.freeze(rules).status_code == 409
    assert flow.api.get(f"/snapshots/{frozen['snapshot_id']}").json() == frozen


@pytest.mark.parametrize("controlled", [True, False])
def test_deadline_uses_word_time_only_for_controlled_render(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any, monkeypatch: Any, controlled: bool
) -> None:
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    original = word(flow.api, store, flow.pid)
    with engine.begin() as conn:
        db.run(
            conn,
            "UPDATE projects SET deadline=(SELECT obtained_at FROM file_versions WHERE id=:v) WHERE id=:p",
            {"v": original["version_id"], "p": flow.pid},
        )
    if controlled:
        configure(monkeypatch, flow.parse_runner)
    else:
        response = _upload(flow.api, store, flow.pid, PDF, role="body", source_word=original["version_id"])[1]
        assert response.status_code == 200, response.text
    drain(flow.parse_runner, engine)
    with engine.connect() as conn:
        flow.body = current_materials.active_body(conn, flow.pid)
        assert db.scalar(
            conn,
            "SELECT obtained_at>(SELECT deadline FROM projects WHERE id=:p) FROM file_versions WHERE id=:v",
            {"p": flow.pid, "v": flow.body},
        )
    response = flow.freeze(rules)
    assert response.status_code == (200 if controlled else 422), response.text
    if not controlled:
        assert response.json()["code"] == "version_after_deadline"


def test_pdf_upload_opened_for_old_word_cannot_adopt_after_word_update(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    api, pid, _runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    sha = hashlib.sha256(PDF).hexdigest()
    session = api.post(
        f"/projects/{pid}/uploads",
        {
            "original_name": "此稿.pdf",
            "role": "body",
            "byte_size": len(PDF),
            "sha256": sha,
            "media_type": "application/pdf",
            "source_word_version_id": original["version_id"],
        },
    ).json()
    updated = word(api, store, pid, "新的 Word", original["file_id"])
    from bidwb.storage import staging_key

    upload = next(i for i, u in store._uploads.items() if u.key == staging_key(session["upload_id"]))
    etag = store.put_part(upload, 1, PDF)
    response = api.post(f"/uploads/{session['upload_id']}/complete", {"sha256": sha, "parts": [{"part_number": 1, "etag": etag}]})
    assert response.status_code == 200, response.text
    with engine.connect() as conn:
        assert current_materials.active_body(conn, pid) == updated["version_id"]
        assert db.scalar(conn, "SELECT count(*) FROM word_pdf_links") == 1
        assert db.scalar(conn, "SELECT count(*) FROM word_pdf_adoptions") == 0


def test_word_link_scope_rejects_other_project_and_wrong_role(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    api, pid, _runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    from tests.test_files_and_parse import PROJECT

    other = api.post("/projects", PROJECT).json()["project_id"]
    body = {
        "original_name": "补交.pdf",
        "role": "body",
        "byte_size": len(PDF),
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "media_type": "application/pdf",
        "source_word_version_id": original["version_id"],
    }
    assert api.post(f"/projects/{other}/uploads", body).status_code == 404
    assert api.post(f"/projects/{pid}/uploads", {**body, "role": "tender"}).status_code == 422


def test_word_pending_pdf_points_to_materials_not_analysis_retry(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    word(flow.api, store, flow.pid)
    drain(flow.parse_runner, engine)
    status = flow.api.get(f"/projects/{flow.pid}/pipeline").json()
    assert status["word_pdf_required"] is True
    overview = next(project for project in flow.api.get("/projects").json() if project["project_id"] == flow.pid)
    assert overview["summary"]["next_action"]["target"] == "materials"
    assert overview["summary"]["next_action"]["key"] == "upload_materials"


def test_retry_uses_method_configuration_without_api_queue_mounts(
    api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any
) -> None:
    api, pid, runner = setup(api_factory, make_member, worker_container, engine)
    original = word(api, store, pid)
    drain(runner, engine)
    path = f"/files/{original['version_id']}/word:retry"
    assert api.post(path, {}).status_code == 503
    worker_container.settings.word_renderer_fingerprint = "a" * 64
    assert worker_container.settings.word_input_dir is None and worker_container.settings.word_output_dir is None
    assert api.post(path, {}).status_code == 200
    response = api.post(path, {})
    assert response.status_code == 409 and response.json()["code"] == "word_conversion_running"
