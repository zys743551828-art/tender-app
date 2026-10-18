"""轮询跨过规则任务提交时，不用旧计划拼出可冻结的输入。"""

from typing import Any

import pytest

from bidwb.services import pipeline
from tests.test_files_and_parse import _setup

pytestmark = pytest.mark.integration


def test_completed_task_after_package_read_is_reported_as_pending_refresh(api_factory: Any, make_member: Any, monkeypatch: Any) -> None:
    api, pid = _setup(api_factory, make_member)
    plan = pipeline._Plan(parse="done", body_id="ver_body_race", tender_ids=["ver_tender_race"])
    plan.rules_job = {"id": "job_rules_race", "state": "succeeded"}  # type: ignore[assignment]
    monkeypatch.setattr(pipeline, "_inspect", lambda _conn, _project_id: plan)
    result = api.get(f"/projects/{pid}/pipeline")
    assert result.status_code == 200, result.text
    status = result.json()
    assert status["stage"] == "running"
    assert next(s for s in status["steps"] if s["key"] == "rules")["state"] == "running"
    assert status["snapshot_id"] is None
