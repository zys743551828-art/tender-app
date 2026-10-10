"""证据按文档顺序读出（资料入库先后、块顺序），与同内容并发入库不撞唯一约束（真实 PG）。"""

from __future__ import annotations

import threading
import time

import pytest

from bidwb import db, tasks
from bidwb.ai.handlers import _load_evidence
from bidwb.messaging import InMemoryBus
from bidwb.services import files
from bidwb.workers.handlers import default_handlers
from bidwb.workers.runner import WorkerRunner
from tests.pdfs import make_pdf
from tests.test_files_and_parse import _setup, _upload

pytestmark = pytest.mark.integration


def test_evidence_reads_back_in_document_order(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    lines = [f"第{n}节 内容{n}" for n in "一二三四五六七八"]
    _upload(api, store, pid, make_pdf([lines[:4], lines[4:]]))
    _upload(api, store, pid, make_pdf([["补遗 第九节 内容九"]]), name="补遗.pdf", role="supplement", key="supplement-0001")
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        assert tasks.relay_outbox(conn, bus.producer()) == 2
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="worker-parse")
    while runner.poll_once():
        pass
    with engine.connect() as conn:
        versions = [r["id"] for r in db.all_(conn, "SELECT id FROM file_versions WHERE project_id=:p", {"p": pid})]
        quotes = [e.quote for e in _load_evidence(conn, pid, versions)]
        seqs = db.all_(conn, "SELECT seq FROM evidence WHERE project_id=:p ORDER BY seq", {"p": pid})
    assert [q.split("\n")[0][:3] for q in quotes] == [
        "第一节",
        "第二节",
        "第三节",
        "第四节",
        "第五节",
        "第六节",
        "第七节",
        "第八节",
        "补遗 ",
    ]
    assert sorted(r["seq"] for r in seqs) == [0, 0, 1, 2, 3, 4, 5, 6, 7]  # 每次解析从 0 起，跨页递增


def test_same_content_registered_concurrently_yields_one_artifact(engine) -> None:  # type: ignore[no-untyped-def]
    key = "content/race-test"
    results: list[str] = []
    first_inserted = threading.Event()

    def first() -> None:
        with db.transaction(engine) as conn:
            results.append(files._artifact_for(conn, sha256="a" * 64, size=1, media_type="application/pdf", key=key, status="committed"))
            first_inserted.set()
            time.sleep(0.5)  # 先到的事务还没提交时，后到的一方在插入处等待

    def second() -> None:
        first_inserted.wait(5)
        with db.transaction(engine) as conn:
            results.append(files._artifact_for(conn, sha256="a" * 64, size=1, media_type="application/pdf", key=key, status="committed"))

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM artifacts WHERE object_key=:k", {"k": key}) == 1
    assert len(results) == 2 and results[0] == results[1]
