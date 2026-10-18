"""异常进程退出后的临时队列回收，不修改业务档案或活动操作。"""

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bidwb.word_conversion import ORPHAN_INPUT_SECONDS, cleanup_stale_inputs
from bidwb.workers.runner import WorkerRunner


def old(path: Path) -> None:
    path.write_bytes(b"synthetic queue copy")
    timestamp = time.time() - ORPHAN_INPUT_SECONDS - 60
    os.utime(path, (timestamp, timestamp))


def test_cleans_only_old_groups_and_preserves_fresh_or_foreign_files(tmp_path: Path) -> None:
    for suffix in ("docx", "request.json", "request.tmp"):
        old(tmp_path / f"{'a' * 32}.{suffix}")
    old(tmp_path / f"{'b' * 32}.docx")
    (tmp_path / f"{'b' * 32}.request.json").write_bytes(b"active request")
    old(tmp_path / "original-business.docx")
    old(tmp_path / f"{'c' * 32}.pdf")
    assert cleanup_stale_inputs(tmp_path) == 3
    assert {p.name for p in tmp_path.iterdir()} == {
        f"{'b' * 32}.docx",
        f"{'b' * 32}.request.json",
        "original-business.docx",
        f"{'c' * 32}.pdf",
    }
    assert cleanup_stale_inputs(tmp_path) == 0


def test_preserves_entire_group_with_nonregular_member(tmp_path: Path) -> None:
    old(tmp_path / f"{'a' * 32}.docx")
    (tmp_path / f"{'a' * 32}.request.json").mkdir()
    assert cleanup_stale_inputs(tmp_path) == 0
    assert (tmp_path / f"{'a' * 32}.docx").exists()


@pytest.mark.parametrize("job_class", ["parse", "ai"])
def test_idle_parse_worker_also_reclaims_orphans(tmp_path: Path, monkeypatch: Any, job_class: str) -> None:
    old(tmp_path / f"{'a' * 32}.docx")
    stop = threading.Event()
    settings = SimpleNamespace(worker_id="cleanup-test", word_input_dir=tmp_path)
    runner = WorkerRunner(SimpleNamespace(settings=settings), job_class, SimpleNamespace(close=lambda: None), {}, "cleanup-test")
    monkeypatch.setattr(runner, "poll_once", lambda _timeout: stop.set())
    runner.run_forever(stop)
    assert (tmp_path / f"{'a' * 32}.docx").exists() is (job_class != "parse")
