"""资料上传 → 校验 → 文件版本 → 解析任务 → 证据 → 检索，端到端（真实 PG、内存存储与总线）。"""

from __future__ import annotations

import hashlib
import json

import pytest

from bidwb import db, tasks
from bidwb.messaging import InMemoryBus
from bidwb.runtime import Container
from bidwb.services.snapshots import _coverage_gaps
from bidwb.storage import MemoryObjectStore, content_key
from bidwb.workers.handlers import default_handlers
from bidwb.workers.runner import WorkerRunner
from tests.pdfs import make_pdf

pytestmark = pytest.mark.integration

PROJECT = {
    "title": "合肥某道路工程",
    "tender_number": None,
    "lot": "一标段",
    "round": 1,
    "region": "合肥",
    "engineering_type": "市政道路",
    "deadline": None,
}


def _setup(api_factory, make_member):  # type: ignore[no-untyped-def]
    make_member("lead")
    api = api_factory().login("lead")
    return api, api.post("/projects", PROJECT).json()["project_id"]


def _upload(
    api,
    store: MemoryObjectStore,
    pid: str,
    data: bytes,
    *,
    name: str = "招标文件.pdf",
    role: str = "tender",  # type: ignore[no-untyped-def]
    media: str = "application/pdf",
    declared_sha: str | None = None,
    key: str | None = None,
    version_of: str | None = None,
):
    init = api.post(
        f"/projects/{pid}/uploads",
        {
            "original_name": name,
            "role": role,
            "byte_size": len(data),
            "sha256": declared_sha or hashlib.sha256(data).hexdigest(),
            "media_type": media,
            **({"version_of_file_id": version_of} if version_of else {}),
        },
        key=key,
    )
    assert init.status_code == 200, init.text
    session = init.json()
    oss_id = next(iter(store._uploads))
    part_size = session["part_bytes"]
    etags = []
    for part in session["parts"]:
        n = part["part_number"]
        etags.append({"part_number": n, "etag": store.put_part(oss_id, n, data[(n - 1) * part_size : n * part_size])})
    return session, api.post(f"/uploads/{session['upload_id']}/complete", {"sha256": hashlib.sha256(data).hexdigest(), "parts": etags})


def file_id_of(api, pid: str, version_id: str) -> str:  # type: ignore[no-untyped-def]
    return next(v["file_id"] for v in api.get(f"/projects/{pid}/files").json() if v["version_id"] == version_id)


def test_upload_commits_content_addressed_version_and_enqueues_parse(api_factory, make_member, store, engine) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    data = make_pdf([["第一章 工程概况", "工期一百八十日历天。"]])
    _, done = _upload(api, store, pid, data)
    assert done.status_code == 200, done.text
    version = done.json()
    sha = hashlib.sha256(data).hexdigest()
    assert version["artifact"]["sha256"] == sha and version["supersedes"] is None and version["association_status"] == "pending"
    assert store.objects[content_key(sha)] == data  # 最终键内容寻址
    assert not [k for k in store.objects if k.startswith("staging/")]  # 暂存对象已清理
    with engine.connect() as conn:
        job = db.one(conn, "SELECT kind,state,input_json FROM jobs")
        assert job["kind"] == "parse" and job["state"] == "queued" and job["input_json"] == {"file_version_id": version["version_id"]}
        assert db.scalar(conn, "SELECT count(*) FROM outbox_events WHERE topic='job.parse'") == 1


def test_complete_is_replay_safe_and_explicit_version_supersedes(api_factory, make_member, store) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    first_session, first = _upload(api, store, pid, make_pdf([["第一版 内容充足充足"]]))
    assert first.json()["version_number"] == 1 and first.json()["new_file"] is True and first.json()["duplicate"] is False
    again = api.post(
        f"/uploads/{first_session['upload_id']}/complete",
        {"sha256": first.json()["artifact"]["sha256"], "parts": [{"part_number": 1, "etag": "x"}]},
    )
    assert again.status_code == 200 and again.json()["version_id"] == first.json()["version_id"]
    assert again.json()["new_file"] is True and again.json()["duplicate"] is False
    # 没有 version_of_file_id：即使用途与原名都相同，也是新的逻辑文件
    _, separate = _upload(api, store, pid, make_pdf([["另一份 内容充足充足"]]), key="separate-upload-0001")
    assert separate.json()["supersedes"] is None and separate.json()["file_id"] != first.json()["file_id"]
    assert separate.json()["version_number"] == 1 and separate.json()["new_file"] is True
    # 显式声明才成为下一版本
    _, second = _upload(api, store, pid, make_pdf([["第二版 内容充足充足"]]), key="second-upload-0001", version_of=first.json()["file_id"])
    assert second.json()["supersedes"] == first.json()["version_id"] and second.json()["file_id"] == first.json()["file_id"]
    assert second.json()["version_number"] == 2 and second.json()["new_file"] is False and second.json()["duplicate"] is False
    listed = {v["version_id"]: v for v in api.get(f"/projects/{pid}/files").json()}
    assert (
        len(listed) == 3
        and listed[second.json()["version_id"]]["version_number"] == 2
        and listed[separate.json()["version_id"]]["version_number"] == 1
    )
    assert "duplicate" not in listed[first.json()["version_id"]]


def test_version_of_file_id_must_be_same_project_and_role(api_factory, make_member, store) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    first = _upload(api, store, pid, make_pdf([["第一版 内容充足充足"]]))[1].json()
    other_pid = api.post("/projects", {**PROJECT, "title": "另一个项目"}).json()["project_id"]
    other = _upload(api, store, other_pid, make_pdf([["别的项目 内容充足"]]))[1].json()

    def init(project: str, file_id: str | None, role: str = "tender", data: bytes = b"x" * 100):  # type: ignore[no-untyped-def]
        return api.post(
            f"/projects/{project}/uploads",
            {
                "original_name": "a.pdf",
                "role": role,
                "byte_size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "media_type": "application/pdf",
                "version_of_file_id": file_id,
            },
        )

    assert init(pid, "fil_nonexistent").json()["code"] == "version_of_invalid"
    assert init(pid, other["file_id"]).status_code == 422  # 别的项目的文件
    wrong_role = init(pid, first["file_id"], role="body")
    assert wrong_role.status_code == 422 and wrong_role.json()["code"] == "version_of_invalid"
    assert init(pid, first["file_id"]).status_code == 200
    assert init(pid, None).status_code == 200  # 显式 null 等同缺省


def test_init_upload_idempotent_and_conflict(api_factory, make_member, store) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    body = {"original_name": "a.pdf", "role": "tender", "byte_size": 100, "sha256": "a" * 64, "media_type": "application/pdf"}
    one = api.post(f"/projects/{pid}/uploads", body, key="init-upload-0001").json()
    two = api.post(f"/projects/{pid}/uploads", body, key="init-upload-0001").json()
    assert one["upload_id"] == two["upload_id"] and len(store._uploads) == 1
    changed = api.post(f"/projects/{pid}/uploads", {**body, "byte_size": 101}, key="init-upload-0001")
    assert changed.status_code == 409


def test_server_side_recompute_catches_wrong_bytes_with_matching_claim(api_factory, make_member, store, engine) -> None:  # type: ignore[no-untyped-def]
    """浏览器声称校验值正确，但实际上传的字节不同：服务端复算必须发现。"""
    api, pid = _setup(api_factory, make_member)
    real = make_pdf([["真实内容 真实内容"]])
    claimed = hashlib.sha256(real).hexdigest()
    init = api.post(
        f"/projects/{pid}/uploads",
        {"original_name": "a.pdf", "role": "tender", "byte_size": len(real), "sha256": claimed, "media_type": "application/pdf"},
    ).json()
    oss_id = next(iter(store._uploads))
    tampered = bytes([real[0] ^ 1]) + real[1:]
    etag = store.put_part(oss_id, 1, tampered)
    done = api.post(f"/uploads/{init['upload_id']}/complete", {"sha256": claimed, "parts": [{"part_number": 1, "etag": etag}]})
    assert done.status_code == 422 and done.json()["code"] == "content_mismatch"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT status FROM artifacts") == "quarantined"  # 隔离记录在 422 之后仍然保留
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='upload.quarantine'") == 1
    assert content_key(claimed) not in store.objects


def test_upload_rejects_invalid_input(api_factory, make_member) -> None:  # type: ignore[no-untyped-def]
    make_member("lead")
    lead = api_factory().login("lead")
    pid = lead.post("/projects", PROJECT).json()["project_id"]
    body = {"original_name": "a.pdf", "role": "tender", "byte_size": 10, "sha256": "a" * 64, "media_type": "application/pdf"}
    assert lead.post(f"/projects/{pid}/uploads", {**body, "media_type": "text/html"}).json()["code"] == "media_type_not_allowed"
    assert lead.post(f"/projects/{pid}/uploads", {**body, "byte_size": 104857601}).status_code == 422


def test_file_content_range_and_etag(api_factory, make_member, store) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    data = make_pdf([["第一章 内容充足充足充足"]])
    _, done = _upload(api, store, pid, data)
    url = f"/files/{done.json()['version_id']}/content"
    full = api.get(url)
    assert full.status_code == 200 and full.content == data and full.headers["Accept-Ranges"] == "bytes"
    part = api.get(url, headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == data[:10] and part.headers["Content-Range"] == f"bytes 0-9/{len(data)}"
    assert api.get(url, headers={"Range": "bytes=-5"}).content == data[-5:]
    assert api.get(url, headers={"Range": f"bytes={len(data)}-"}).status_code == 416
    assert api.get(url, headers={"If-None-Match": full.headers["ETag"]}).status_code == 304
    other = api_factory()
    assert other.get(url).status_code == 401


def test_parse_pipeline_end_to_end_under_restricted_worker_role(
    api_factory, make_member, store, engine, worker_container: Container
) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    data = make_pdf([["第一章 工程概况", "本工程工期为一百八十日历天。"], ["第二章 质量标准", "质量标准为合格。"], []])
    _, done = _upload(api, store, pid, data)
    version_id = done.json()["version_id"]
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        assert tasks.relay_outbox(conn, bus.producer()) == 1
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="worker-parse")
    assert runner.poll_once() is True
    with engine.connect() as conn:
        job = db.one(conn, "SELECT state,attempt,output_artifact_id FROM jobs")
        assert job["state"] == "succeeded" and job["attempt"] == 1
        parse = db.one(conn, "SELECT coverage,page_count,gaps_json FROM parses")
        assert parse["coverage"] == "partial" and parse["page_count"] == 3 and parse["gaps_json"] == ["page_3:no_text_layer"]
        assert db.scalar(conn, "SELECT count(*) FROM evidence") == 2
    # 同一条消息重复投递：被取出但因去重而不再执行
    bus.redeliver(0)
    assert runner.poll_once() is True
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM evidence") == 2
        assert db.scalar(conn, "SELECT count(*) FROM job_events WHERE kind='claimed'") == 1
    assert version_id


def test_image_gap_persists_in_artifact_and_snapshot_coverage(api_factory, make_member, store, engine, worker_container: Container) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    _, done = _upload(api, store, pid, make_pdf([["-24-"], ["第一章 施工部署"]], image_first=True))
    version_id = done.json()["version_id"]
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        tasks.relay_outbox(conn, bus.producer())
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="worker-parse")
    assert runner.poll_once() is True
    with engine.connect() as conn:
        parse = db.one(conn, "SELECT coverage,gaps_json,artifact_id FROM parses")
        assert parse["coverage"] == "partial" and parse["gaps_json"] == ["page_1:raster_images_unread"]
        key = db.scalar(conn, "SELECT object_key FROM artifacts WHERE id=:a", {"a": parse["artifact_id"]})
        payload = json.loads(store.get(key))
        assert payload["source_sha256"] == done.json()["artifact"]["sha256"]
        assert payload["file_version_id"] == version_id and payload["parser_version"] == "pdfium-1.2"
        assert payload["coverage_scope"] == "native_text_and_raster_presence"
        assert [p["physical_page"] for p in payload["pages"]] == [1, 2]
        assert payload["pages"][0]["issues"] == ["raster_images_unread"]
        assert payload["pages"][1]["issues"] == []
        assert _coverage_gaps(conn, pid, [version_id]) == [f"{version_id}:partial", f"{version_id}:page_1:raster_images_unread"]
        assert db.scalar(conn, "SELECT count(*) FROM evidence WHERE file_version_id=:v", {"v": version_id}) == 2


def test_unreadable_file_fails_parse_task_with_reason_and_no_parse_record(
    api_factory, make_member, store, engine, worker_container: Container
) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    _upload(api, store, pid, make_pdf([[], []]))  # 没有任何文字层：扫描件
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        assert tasks.relay_outbox(conn, bus.producer()) == 1
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="worker-parse")
    assert runner.poll_once() is True
    with engine.connect() as conn:
        job = db.one(conn, "SELECT state,error_code FROM jobs")
        assert job["state"] == "failed" and job["error_code"] == "parse_unreadable"
        assert db.scalar(conn, "SELECT count(*) FROM parses") == 0
    listed = api.get(f"/projects/{pid}/tasks").json()
    assert listed[0]["state"] == "failed" and "扫描件" in (listed[0]["message"] or "")


def test_search_without_snapshot_covers_current_materials(api_factory, make_member, store, engine, worker_container: Container) -> None:  # type: ignore[no-untyped-def]
    """录入第一批事实时还没有任何一轮诊断：不给 snapshot_id 时检索项目当前资料；给了不存在的输入仍是 404。"""
    api, pid = _setup(api_factory, make_member)
    _upload(api, store, pid, make_pdf([["第一章 工程概况", "本工程工期为一百八十日历天。"]]))
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        tasks.relay_outbox(conn, bus.producer())
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="worker-parse")
    assert runner.poll_once() is True
    found = api.post(f"/projects/{pid}/search", json={"query": "工期", "top_k": 5, "mode": "keyword"})
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["snapshot_id"] is None and body["hits"] and "工期" in body["hits"][0]["evidence"]["quote"]
    missing = api.post(f"/projects/{pid}/search", json={"snapshot_id": "snp_nope", "query": "工期", "top_k": 5, "mode": "keyword"})
    assert missing.status_code == 404
