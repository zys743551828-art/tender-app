"""Native task/job/Worker/publication/notification chain over nonowner PG17.

All model HTTP is explicit MockTransport. Original objects are synthetic fixture
bytes; this is publication protocol evidence, not model quality or exact-package input.
"""
# ruff: noqa: F401,F811

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb
from test_authoring_generation_batches_pg import batch_database, cookie, database, headers
from test_authoring_generation_batches_pg import env as chapter_sources

from apps.api import main, task_routes
from apps.api.views import bid_etag
from apps.worker import engine
from packages.assistant import coordinator, jobs
from packages.authoring import generation, repository
from packages.authoring.content import schema_digest_for
from packages.domain.runtime import Command, DomainError, assert_role, audit, clean, connection, sha
from packages.lifecycle.service import change as change_lifecycle
from packages.tasks import authoring_result, runner, runs
from packages.tasks.models import RunView, TaskAuthoringResult

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated task chapter PG17 required",
)


@pytest.fixture
def case(chapter_sources):
    value = chapter_sources
    app = value["client"].app
    app.include_router(task_routes.router)
    app.add_api_route("/api/v1/operations/{operation_id}", main.operation, methods=["GET"])
    app.add_api_route("/api/v1/operations/{operation_id}/cancel", main.cancel, methods=["POST"])
    assert_role()
    assert_role(True)
    with connection() as c:
        condition = bid_etag(c, value["bid"])
    response = value["client"].post(
        f"/api/v1/bids/{value['bid']}/task-definitions",
        json={
            "name": "合成章节发布任务",
            "task_kind": "chapter_suggestion",
            "section_id": str(value["sections"][0]["id"]),
            "instructions": "只提出有来源的文字修改，保留表格图片，须人工预览采纳",
            "source_selection": {
                "mode": "selected_versions",
                "version_ids": [value["ids"]["version"]],
            },
        },
        headers=headers(value, condition=condition),
    )
    assert response.status_code == 201, response.text
    value["template_response"] = response
    value["template"] = response.json()
    value["key"] = uuid4().hex
    accepted = launch(value, key=value["key"])
    assert accepted.status_code == 202, accepted.text
    value["accepted"] = accepted
    value["task"] = accepted.json()
    value["job_id"] = UUID(value["task"]["frozen_manifest"]["assistant_job_id"])
    with connection() as c:
        native = jobs.job(c, value["job_id"])
        value["message"] = c.execute(
            "SELECT payload FROM outbox WHERE operation_id=%s AND topic='tender.task.assistant.v1'",
            (native["operation_id"],),
        ).fetchone()["payload"]
        plan = native["input_manifest"]["plan"]
        paragraph = next(n for n in plan["original_content"]["content"] if n["type"] == "paragraph")
        replacement = deepcopy(paragraph)
        replacement["content"] = [{"type": "text", "text": "合成原页支持的修改建议，尚未采纳"}]
        value["raw"] = {
            "node_id": paragraph["attrs"]["id"],
            "before_digest": sha(paragraph),
            "replacement": replacement,
            "evidence_ids": [value["ids"]["evidence"]],
        }
    assert current(value)["state"] == "queued"
    assert not value["calls"]
    yield value


def launch(case, *, key=None, rerun=False):
    return case["client"].post(
        f"/api/v1/bids/{case['bid']}/task-definitions/{case['template']['id']}/runs",
        json={"rerun": rerun},
        headers=headers(case, key=key, condition=case["template_response"].headers["etag"]),
    )


def current(case):
    response = case["client"].get(
        f"/api/v1/bids/{case['bid']}/task-runs/{case['task']['id']}", headers=cookie(case["actor"])
    )
    assert response.status_code == 200, response.text
    RunView.model_validate(response.json())
    return response.json()


def complete(case, *, publish=True):
    before = len(case["calls"])
    engine.handle(case["message"])
    engine.handle(case["message"])
    assert len(case["calls"]) == before + 1
    if publish:
        coordinator.tick([case["job_id"]])
    return current(case)


def notify(case):
    with connection() as c:
        first = runs.notify(c, case["bid"], UUID(case["task"]["id"]))
    with connection() as c:
        assert not runs.notify(c, case["bid"], UUID(case["task"]["id"]))
    response = case["client"].get(
        f"/api/v1/bids/{case['bid']}/task-notifications", headers=cookie(case["actor"])
    )
    assert response.status_code == 200, response.text
    return first, response.json()["items"]


def export(case, name, value):
    target = os.environ.get("TASK_CHAPTER_HTTP_EXPORT")
    if target:
        if isinstance(value, dict) and "frozen_manifest" in value:
            version = case["client"].get(
                f"/api/v1/bids/{case['bid']}/task-definitions/{case['template']['id']}/versions/{value['definition_version_id']}",
                headers=cookie(case["actor"]),
            )
            operation = case["client"].get(
                "/api/v1/operations/" + value["root_operation_id"],
                headers=cookie(case["actor"]),
            )
            assert version.status_code == operation.status_code == 200
            proposal = None
            if value["result"] and value["result"]["action_ref"]:
                response = case["client"].get(
                    value["result"]["action_ref"], headers=cookie(case["actor"])
                )
                assert response.status_code == 200
                proposal = response.json()
            value = {
                "run": value,
                "template_version": version.json(),
                "operation": operation.json(),
                "operation_etag": operation.headers["etag"],
                "proposal": proposal,
            }
        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(
            json.dumps(clean(value), ensure_ascii=False, indent=2) + "\n"
        )


def test_candidate_is_not_task_success_until_real_proposal_and_one_notification(case):
    export(case, "queued", current(case))
    pending = complete(case, publish=False)
    assert pending["state"] == "awaiting_publication", pending
    assert pending["result"]["candidate_digest"]
    assert pending["result"]["publication_state"] == "pending"
    assert pending["result"]["action_id"] is None
    assert notify(case) == (False, [])
    repeated = launch(case, key=case["key"])
    assert repeated.status_code == 202 and repeated.headers["Idempotent-Replayed"] == "true"
    assert (
        repeated.json()["id"] == pending["id"]
        and repeated.json()["state"] == "awaiting_publication"
    )
    rerun = launch(case, rerun=True)
    assert rerun.status_code == 202 and rerun.json()["id"] == pending["id"]
    assert rerun.headers["Task-Run-Reused"] == "true"
    coordinator.tick([case["job_id"]])
    coordinator.tick([case["job_id"]])
    result = current(case)
    assert result["state"] == "succeeded", result
    domain = TaskAuthoringResult.model_validate(result["result"])
    assert domain.publication_state == "published" and domain.action_id
    preview = case["client"].get(domain.action_ref, headers=cookie(case["actor"]))
    assert preview.status_code == 200 and preview.json()["job_id"] == str(domain.job_id)
    assert preview.json()["preview"]["section_id"] == str(domain.section_id)
    first, notices = notify(case)
    assert first and len(notices) == 1 and notices[0]["payload"]["state"] == "succeeded"
    with connection() as c:
        assert repository.draft_view(c, case["bid"], case["draft"])["revision"] == 1
        assert (
            c.execute(
                "SELECT count(*) AS n FROM assistant_jobs WHERE bid_id=%s", (case["bid"],)
            ).fetchone()["n"]
            == 1
        )
    assert len(case["calls"]) == 1
    export(case, "published", result)
    export(case, "awaiting-publication", pending)
    export(case, "template", case["template"])
    export(case, "proposal", preview.json())
    export(case, "notifications", notices)


@pytest.mark.parametrize("change", ["section", "fact", "source"])
def test_real_publication_rejects_changed_inputs_without_success_notification(case, change):
    complete(case, publish=False)
    if change == "section":
        with connection() as c:
            content = deepcopy(case["sections"][0]["content"])
            content["attrs"]["title"] = "明确修改后的章节"
            repository.save_draft(
                c,
                case["bid"],
                case["draft"],
                case["actor"],
                {
                    "base_draft_revision": 1,
                    "changes": [
                        {
                            "section_id": str(case["sections"][0]["id"]),
                            "base_section_revision": 1,
                            "schema_digest": schema_digest_for(content),
                            "content": content,
                        }
                    ],
                },
                repository.draft_etag(case["draft"], 1),
            )
    elif change == "fact":
        from packages.domain.fact_sets import replace_set

        with connection() as c:
            replace_set(
                c,
                case["bid"],
                case["actor"],
                "合成后续事实",
                kind="add",
                new_fact={
                    "subject": "project",
                    "scope": "current bid",
                    "name": "后续明确事实",
                    "value": "变化",
                    "unit": None,
                    "evidence_ids": [case["ids"]["evidence"]],
                    "reason": "原页基础的显式测试变化",
                },
            )
    else:
        with connection() as c:
            c.execute("SELECT pg_advisory_xact_lock(90127,1)")
            c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (UUID(case["ids"]["source"]),),
            )
    coordinator.tick([case["job_id"]])
    result = current(case)
    assert result["state"] == "superseded", result
    assert (
        result["result"]["publication_state"] == "stale" and result["result"]["action_id"] is None
    )
    assert result["error_code"]
    created, notices = notify(case)
    assert created and [n["payload"]["state"] for n in notices] == ["superseded"]
    export(case, "stale-" + change, result)


def test_real_publication_failure_rolls_back_native_proposal_not_model_success(case, monkeypatch):
    complete(case, publish=False)
    original = generation.accept_generated_proposal

    def injected_failure(*args, **kwargs):
        original(*args, **kwargs)
        raise DomainError("EXPLICIT_PUBLICATION_FAILURE", "合成用例：原生提案插入后失败", 422)

    monkeypatch.setattr(generation, "accept_generated_proposal", injected_failure)
    coordinator.tick([case["job_id"]])
    result = current(case)
    assert result["state"] == "failed", result
    assert result["error_code"] == "EXPLICIT_PUBLICATION_FAILURE"
    assert result["result"]["publication_state"] == "failed"
    assert result["result"]["action_id"] is None
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM proposed_actions WHERE bid_id=%s", (case["bid"],)
            ).fetchone()["n"]
            == 0
        )
    assert notify(case)[1][0]["payload"]["state"] == "failed"
    export(case, "failed", result)


def test_unknown_fee_blocks_new_rerun_key_and_stays_explained(case):
    case["mode"] = "timeout"
    result = complete(case)
    assert result["state"] == "reconciliation_required", result
    assert result["error_code"] == "MODEL_CALL_REQUIRES_RECONCILIATION"
    assert result["result"]["action_id"] is None
    for rerun in (False, True):
        response = launch(case, rerun=rerun)
        assert response.status_code == 409
        assert response.json()["code"] == "MODEL_CALL_REQUIRES_RECONCILIATION"
    replay = launch(case, key=case["key"])
    assert replay.status_code == 202 and replay.json()["id"] == result["id"]
    assert replay.json()["state"] == "reconciliation_required"
    assert len(case["calls"]) == 1
    assert notify(case)[1][0]["payload"]["state"] == "reconciliation_required"
    export(case, "unknown-fee", result)


def test_cancel_original_operation_then_worker_converges_without_model(case):
    path = "/api/v1/operations/" + case["task"]["root_operation_id"]
    operation = case["client"].get(path, headers=cookie(case["actor"]))
    request_headers = headers(case, condition=operation.headers["etag"])
    body = {"reason": "明确停止原章节候选", "cancel_pending_same_input": False}
    cancelled = case["client"].post(path + "/cancel", json=body, headers=request_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert current(case)["state"] == "cancel_requested"
    engine.handle(case["message"])
    engine.reconcile(once=True)
    coordinator.tick([case["job_id"]])
    result = current(case)
    assert result["state"] == "cancelled", result
    assert not case["calls"] and result["result"]["action_id"] is None
    repeated = case["client"].post(path + "/cancel", json=body, headers=request_headers)
    assert repeated.json() == cancelled.json()
    assert notify(case)[1][0]["payload"]["state"] == "cancelled"
    export(case, "cancelled", result)


@pytest.mark.parametrize(
    "field", ["assistant_job_id", "job_input_digest", "operation_id", "parse_id"]
)
def test_wrong_native_identity_never_projects_an_unrelated_success(case, field):
    complete(case)
    with connection() as c:
        row = c.execute(
            "SELECT * FROM task_runs WHERE id=%s", (UUID(case["task"]["id"]),)
        ).fetchone()
        original = clean(row)
        broken = deepcopy(original)
        if field == "assistant_job_id":
            broken["frozen_manifest"][field] = str(uuid4())
        elif field == "operation_id":
            broken[field] = str(uuid4())
        elif field == "parse_id":
            broken["frozen_manifest"]["context"]["documents"][0]["parse_id"] = str(uuid4())
            f = broken["frozen_manifest"]
            f["input_digest"] = sha(
                {
                    "version_id": f["definition_version_id"],
                    "purpose": f["purpose"],
                    "context": f["context"],
                }
            )
        else:
            broken["frozen_manifest"]["authoring_binding"][field] = "0" * 64
        assert authoring_result.project(c, broken) == ("unknown", authoring_result.ERROR, None)
        assert authoring_result.project(c, original)[0] == "succeeded"


def test_accepted_legacy_job_reference_still_uses_exact_original_history(case):
    complete(case)
    with connection() as c:
        row = c.execute(
            "SELECT * FROM task_runs WHERE id=%s", (UUID(case["task"]["id"]),)
        ).fetchone()
        original = deepcopy(row)
        original["frozen_manifest"].pop("authoring_binding")
        assert authoring_result.project(c, original)[0] == "succeeded"


@pytest.mark.parametrize("publication", ["published", "pending", "unknown_fee"])
def test_closed_project_runner_recovers_original_terminal_notification_only(
    case, publication, monkeypatch
):
    if publication == "unknown_fee":
        case["mode"] = "timeout"
    complete(case, publish=publication != "pending")
    with connection() as c:
        command = Command(c, case["actor"], "project-lifecycle", case["bid"], uuid4().hex, {})
        value = change_lifecycle(
            c, case["bid"], case["actor"], "terminate", "明确停止合成项目", command.id
        )
        command.finish(value)
    coordinator.tick([case["job_id"]])
    expected = {
        "published": "succeeded",
        "pending": "superseded",
        "unknown_fee": "reconciliation_required",
    }[publication]
    assert current(case)["state"] == expected
    before = len(case["calls"])
    after = UUID(int=case["bid"].int - 1)
    result = runner.cycle(after=after, limit=1)
    assert result["processed_projects"] == 1 and result["provider_calls"] == 0
    assert len(case["calls"]) == before
    # Once the original terminal result is notified, the closed project no longer
    # enters discovery. No new template run or implicit reopening is introduced.
    visited = []
    original_tick = runner.coordinator.tick

    def observed_tick(c, *, bid, **kwargs):
        visited.append(bid)
        return original_tick(c, bid=bid, **kwargs)

    monkeypatch.setattr(runner.coordinator, "tick", observed_tick)
    assert runner.cycle(after=after, limit=1)["provider_calls"] == 0
    assert case["bid"] not in visited
    with connection() as c:
        notices = c.execute(
            "SELECT payload FROM audit_entries WHERE bid_id=%s AND event_type='task.notification'",
            (case["bid"],),
        ).fetchall()
        assert [n["payload"]["state"] for n in notices] == [expected]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM task_runs WHERE bid_id=%s", (case["bid"],)
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute("SELECT phase FROM bid_profiles WHERE bid_id=%s", (case["bid"],)).fetchone()[
                "phase"
            ]
            == "terminated"
        )


def test_invalid_model_structure_is_known_failure_without_candidate_or_proposal(case):
    case["mode"] = "invalid"
    result = complete(case)
    assert result["state"] == "failed", result
    assert result["result"]["candidate_digest"] is None
    assert result["result"]["publication_state"] == "pending"
    assert result["result"]["action_id"] is None
    assert notify(case)[1][0]["payload"]["state"] == "failed"
    with connection() as c:
        model = c.execute(
            "SELECT state,usage FROM model_calls WHERE operation_id=%s",
            (UUID(case["task"]["root_operation_id"]),),
        ).fetchone()
        assert model["state"] == "failed" and model["usage"]["billing_state"] == "usage_reported"
    export(case, "model-invalid", result)


def test_withdrawal_before_worker_never_calls_model_or_creates_candidate(case):
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(90127,1)")
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (UUID(case["ids"]["source"]),),
        )
    engine.handle(case["message"])
    coordinator.tick([case["job_id"]])
    result = current(case)
    assert result["state"] == "failed", result
    assert not case["calls"] and result["result"]["candidate_digest"] is None
    assert result["result"]["action_id"] is None
    assert notify(case)[1][0]["payload"]["state"] == "failed"


def test_template_pause_keeps_accepted_original_job_and_published_history(case):
    complete(case, publish=False)
    path = f"/api/v1/bids/{case['bid']}/task-definitions/{case['template']['id']}"
    response = case["client"].post(
        path + "/pause",
        json={"paused": True},
        headers=headers(case, condition=case["template_response"].headers["etag"]),
    )
    assert response.status_code == 200 and response.json()["paused"]
    assert response.json()["active_runs_cancelled"] is False
    coordinator.tick([case["job_id"]])
    value = current(case)
    assert value["state"] == "succeeded"
    assert value["definition_version_id"] == case["template"]["version_id"]
    assert (
        value["frozen_manifest"]["authoring_binding"]
        == case["task"]["frozen_manifest"]["authoring_binding"]
    )
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(90127,1)")
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (UUID(case["ids"]["source"]),),
        )
    # A later source change does not rewrite the historical publication receipt.
    assert current(case)["result"] == value["result"]
    assert notify(case)[1][0]["payload"]["state"] == "succeeded"


def test_legacy_operation_only_notification_cannot_suppress_real_publication_after_closure(case):
    complete(case, publish=False)
    legacy_key = sha({"explicit_legacy_notification_fixture": case["task"]["id"]})
    with connection() as c:
        # Named pre-upgrade receipt fixture: the former task projection incorrectly
        # treated candidate_ready as success. Preserve it, without endorsing it.
        audit(
            c,
            case["actor"],
            case["bid"],
            "task.notification",
            {
                "key": legacy_key,
                "run_id": case["task"]["id"],
                "state": "succeeded",
                "error_code": None,
                "run_ref": f"/api/v1/bids/{case['bid']}/task-runs/{case['task']['id']}",
            },
        )
        assert not runs.notify(c, case["bid"], UUID(case["task"]["id"]))
    coordinator.tick([case["job_id"]])
    assert current(case)["state"] == "succeeded"
    with connection() as c:
        command = Command(c, case["actor"], "project-lifecycle", case["bid"], uuid4().hex, {})
        command.finish(
            change_lifecycle(
                c, case["bid"], case["actor"], "terminate", "明确终止合成项目", command.id
            )
        )
    assert runner.cycle(after=UUID(int=case["bid"].int - 1), limit=1)["provider_calls"] == 0
    with connection() as c:
        notices = c.execute(
            "SELECT payload FROM audit_entries WHERE bid_id=%s AND event_type='task.notification'",
            (case["bid"],),
        ).fetchall()
        markers = c.execute(
            "SELECT payload FROM audit_entries WHERE bid_id=%s AND event_type='task.authoring_notification_bound'",
            (case["bid"],),
        ).fetchall()
        assert len(notices) == 2 and len(markers) == 1
        assert any(n["payload"]["key"] == legacy_key for n in notices)
        assert markers[0]["payload"]["notification_key"] != legacy_key
        assert markers[0]["payload"]["publication_state"] == "published"
        assert markers[0]["payload"]["job_id"] == str(case["job_id"])
        assert not runs.notify(c, case["bid"], UUID(case["task"]["id"]))
