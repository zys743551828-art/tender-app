"""Real nonowner PG/ASGI/native Worker checks; explicit synthetic originals and model HTTP."""
# ruff: noqa: F401,F811

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_task_package_runs_pg import (
    TestExactPackageTasks as _ManualCases,
)
from test_task_package_runs_pg import (
    api,
    counts,
    create_template,
    current,
    headers,
    requirements,
    selected,
    uid,
    world,
)
from test_task_package_runs_pg import database as manual_database

from apps.worker import engine
from packages.domain import bid_package_scope_review as admission
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import Command, DomainError, audit, connection, sha
from packages.tasks import (
    coordinator,
    package_inputs,
    package_runs,
    package_triggers,
    runner,
    runs,
    templates,
)
from packages.tasks.models import PackageTriggerIntentView, TaskScheduleRecoveryPage

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="new isolated nonowner package trigger PG17 required",
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def database():
    ddl = ROOT / "packages/contracts/sql/task-package-triggers.sql"
    assert (
        os.environ.get("TASK_PACKAGE_TRIGGER_REVIEWED_SQL_SHA")
        == hashlib.sha256(ddl.read_bytes()).hexdigest()
    ), "Review this exact standalone DDL before applying it to a new isolated database"
    generator = manual_database.__wrapped__()
    value = next(generator)
    try:
        if (
            value["owner"]
            .execute("SELECT to_regclass('design.task_package_trigger_intents') AS n")
            .fetchone()["n"]
            is None
        ):
            value["owner"].execute(ddl.read_text())
        yield value
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def automatic(case, mode="material_updated"):
    body = {
        "name": "Synthetic explicit saved-package trigger",
        "task_kind": "denial_check",
        "instructions": "仅核对本次明确保存的原包，不改最新包、不确认、不提交",
        "source_selection": {"mode": "exact_package_trigger", "input": selected(case)},
        "trigger": {"mode": mode, **({"cron": "0 9 * * *"} if mode == "schedule" else {})},
    }
    return create_template(case, configuration=body)


def material_event(case, *, dispatch=True):
    bid, actor = case["scope"][0], case["w"]["actor"]
    with connection() as c:
        # This is a synthetic persisted producer event, not an invented browser event.
        snapshot = uuid4()
        revision = c.execute(
            "SELECT coalesce(max(revision),0)+1 AS n FROM material_snapshots WHERE bid_id=%s",
            (bid,),
        ).fetchone()["n"]
        c.execute(
            "INSERT INTO material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,%s,'{}',%s)",
            (snapshot, bid, revision, sha(str(snapshot))),
        )
        c.execute("UPDATE bid_profiles SET current_material_id=%s WHERE bid_id=%s", (snapshot, bid))
        command = Command(
            c,
            actor,
            "synthetic-material-event",
            UUID(bid),
            uuid4().hex,
            {"snapshot_id": str(snapshot)},
        )
        audit(
            c,
            actor,
            bid,
            "materials.committed",
            {"snapshot_id": snapshot, "review_request_id": None},
            command.id,
        )
        command.finish({"snapshot_id": str(snapshot)})
        event = c.execute(
            "SELECT id FROM audit_entries WHERE bid_id=%s AND command_id=%s AND event_type='materials.committed'",
            (bid, command.id),
        ).fetchone()["id"]
        values = (
            coordinator.material_committed(c, bid=UUID(bid), event_id=event) if dispatch else []
        )
    return event, values


def process(case, pending):
    assert pending["state"] == "pending", pending
    value = package_triggers.process(UUID(case["scope"][0]), UUID(pending["intent_id"]))
    PackageTriggerIntentView.model_validate(value)
    return value


def task(case, value):
    response = case["w"]["client"].get(value["run_ref"])
    assert response.status_code == 200, response.text
    return response.json()


def export_http(name, response):
    destination = os.environ.get("TASK_PACKAGE_TRIGGER_HTTP_EXPORT")
    if not destination:
        return
    record = {
        "fixture_kind": "actual ASGI response over synthetic package/model data",
        "request": {
            "method": response.request.method,
            "path": response.request.url.path,
            "body": json.loads(response.request.content) if response.request.content else None,
            "headers": {
                key: response.request.headers[key]
                for key in ("idempotency-key", "if-match")
                if key in response.request.headers
            },
        },
        "status": response.status_code,
        "headers": {
            key: response.headers[key]
            for key in ("etag", "idempotent-replayed", "task-run-reused")
            if key in response.headers
        },
        "data": response.json(),
    }
    (Path(destination) / (name + ".json")).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestExactPackageTriggers:
    original_case = _ManualCases.original_case
    frozen_case = _ManualCases.frozen_case
    execution_case = _ManualCases.execution_case
    prepared_case = _ManualCases.prepared_case
    exact_inventory_proof_case = _ManualCases.exact_inventory_proof_case
    launch_case = _ManualCases.launch_case
    post = _ManualCases.post
    message = _ManualCases.message
    provider = _ManualCases.provider
    cancel = _ManualCases.cancel

    def test_event_intent_native_worker_notifications_replay_and_exact_input_reuse(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        # Later appends can have smaller UUIDs: API continuation follows creation order.
        intent_ids = iter([UUID(int=2**128 - 2), UUID(int=1)])
        monkeypatch.setattr(package_triggers, "uid", lambda: next(intent_ids))
        baseline = len(case["f"]["calls"])
        template = automatic(case)
        export_http("event-template", template)
        export_http("task-kinds", case["w"]["client"].get("/api/v1/task-kinds"))
        event, values = material_event(case)
        pending = values[0]
        intent_path = (
            f"/api/v1/bids/{case['scope'][0]}/task-package-trigger-intents/{pending['intent_id']}"
        )
        export_http("event-pending", case["w"]["client"].get(intent_path))
        assert len(case["f"]["calls"]) == baseline and counts(case)["native_runs"] == 0
        with connection() as c:
            assert (
                coordinator.material_committed(c, bid=UUID(case["scope"][0]), event_id=event)
                == values
            )
        accepted = process(case, pending)
        export_http("event-accepted", case["w"]["client"].get(intent_path))
        assert accepted["state"] == "accepted" and not accepted["reused"]
        queued = task(case, accepted)
        frozen = queued["frozen_manifest"]
        assert frozen["schema"] == package_inputs.TRIGGER_SCHEMA
        assert frozen["trigger"] == "material_updated" and frozen["trigger_event_id"] == str(event)
        assert (
            frozen["context"]["selection"]
            == template.json()["configuration"]["source_selection"]["input"]
        )
        native = case["w"]["client"].get(frozen["package_review"]["run_ref"]).json()
        calls = self.provider(case, monkeypatch)
        message = self.message(case, native)
        engine.handle_lane("review", message)
        engine.handle_lane("review", message)
        assert len(calls) == 1 and task(case, accepted)["state"] == "succeeded"
        with connection() as c:
            assert runs.notify(c, UUID(case["scope"][0]), UUID(queued["id"]))
            assert not runs.notify(c, UUID(case["scope"][0]), UUID(queued["id"]))
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM stream_events WHERE event_type='task.notification' AND payload->>'run_id'=%s",
                    (queued["id"],),
                ).fetchone()["n"]
                == 1
            )
        notifications = (
            case["w"]["client"].get(f"/api/v1/bids/{case['scope'][0]}/task-notifications").json()
        )
        assert any(item["payload"]["run_id"] == queued["id"] for item in notifications["items"])
        export_http("event-succeeded-run", case["w"]["client"].get(accepted["run_ref"]))
        export_http(
            "event-notifications",
            case["w"]["client"].get(f"/api/v1/bids/{case['scope'][0]}/task-notifications"),
        )
        _, second = material_event(case)
        reused = process(case, second[0])
        assert (
            reused["state"] == "accepted" and reused["reused"] and reused["run_id"] == queued["id"]
        )
        assert counts(case)["native_runs"] == 1 and counts(case)["tasks"] == 1
        history = (
            case["w"]["client"]
            .get(f"/api/v1/bids/{case['scope'][0]}/task-package-trigger-intents")
            .json()
        )
        assert len(history["items"]) == 2 and all(
            row["state"] == "accepted" for row in history["items"]
        )
        path = f"/api/v1/bids/{case['scope'][0]}/task-package-trigger-intents"
        export_http("event-intents", case["w"]["client"].get(path))
        first_page = case["w"]["client"].get(path, params={"limit": 1}).json()
        assert first_page["next_after"] == pending["intent_id"]
        second_page = (
            case["w"]["client"]
            .get(path, params={"limit": 1, "after": first_page["next_after"]})
            .json()
        )
        assert second_page["next_after"] is None
        assert [item["id"] for item in second_page["items"]] == [second[0]["intent_id"]]
        assert case["w"]["client"].get(path, params={"after": str(uuid4())}).status_code == 404

    def test_schedule_once_missed_window_skipped_and_original_due_is_recorded(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        template = automatic(case, "schedule")
        export_http("schedule-template", template)
        owner = case["w"]["database"]["owner"]
        observed = owner.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        owner.execute(
            "UPDATE design.schedules SET next_fire_at=%s WHERE definition_id=%s",
            (observed, template.json()["id"]),
        )
        monkeypatch.setattr(templates, "clock", lambda c: observed)
        with connection() as c:
            pending = coordinator.tick(c, bid=UUID(case["scope"][0]))
        with connection() as c:
            assert coordinator.tick(c, bid=UUID(case["scope"][0])) == []
        accepted = process(case, pending[0])
        assert accepted["state"] == "accepted", accepted
        assert accepted["scheduled_at"] == observed.isoformat()
        assert (
            owner.execute(
                "SELECT count(*) AS n FROM design.schedule_receipts s JOIN design.schedules d ON d.id=s.schedule_id WHERE d.definition_id=%s",
                (template.json()["id"],),
            ).fetchone()["n"]
            == 1
        )
        owner.execute(
            "UPDATE design.schedules SET next_fire_at=%s WHERE definition_id=%s",
            (observed - timedelta(days=3), template.json()["id"]),
        )
        with connection() as c:
            skipped = coordinator.tick(c, bid=UUID(case["scope"][0]))
        assert (
            skipped[0]["automatic_catchup_runs"] == 0 and skipped[0]["run_current_once_ref"] is None
        )
        assert skipped[0]["missed"]["resolution"] == "skipped_reconfirm_exact_input"
        response = case["w"]["client"].get(
            f"/api/v1/bids/{case['scope'][0]}/task-schedule-recoveries"
        )
        TaskScheduleRecoveryPage.model_validate(response.json())
        export_http("schedule-missed", response)
        assert counts(case)["native_runs"] == 1

    @pytest.mark.parametrize("change", ["template", "pause", "close", "source", "event"])
    def test_changes_during_unlocked_original_io_block_without_rebasing(self, launch_case, change):
        case = launch_case
        template = automatic(case)
        _, pending = material_event(case)
        before = counts(case)
        owner = case["w"]["database"]["owner"]

        def mutate():
            if change in ("template", "pause"):
                path = f"/api/v1/bids/{case['scope'][0]}/task-definitions/{template.json()['id']}"
                response = (
                    case["w"]["client"].put(
                        path,
                        json=template.json()["configuration"] | {"name": "Explicit new version"},
                        headers=headers(case["w"], etag=template.headers["etag"]),
                    )
                    if change == "template"
                    else case["w"]["client"].post(
                        path + "/pause",
                        json={"paused": True},
                        headers=headers(case["w"], etag=template.headers["etag"]),
                    )
                )
                assert response.status_code == 200, response.text
            elif change == "close":
                owner.execute(
                    "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                    (case["scope"][0],),
                )
            elif change == "source":
                owner.execute(
                    "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                    (case["w"]["sources"][0],),
                )
            else:
                material_event(case, dispatch=False)

        case["f"]["state"]["during_read"] = mutate
        blocked = process(case, pending[0])
        assert blocked["state"] == "blocked" and blocked["error_code"], blocked
        assert counts(case) == before
        assert blocked["selection"] == template.json()["configuration"]["source_selection"]["input"]
        export_http(
            "blocked-" + change,
            case["w"]["client"].get(
                f"/api/v1/bids/{case['scope'][0]}/task-package-trigger-intents/{pending[0]['intent_id']}"
            ),
        )

    def test_concurrent_resumers_accept_one_native_run(self, launch_case, monkeypatch):
        case = launch_case
        automatic(case)
        _, pending = material_event(case)
        barrier = Barrier(2)
        verify = admission.verify

        def synchronized(observed):
            barrier.wait(timeout=20)
            value = verify(observed)
            barrier.wait(timeout=20)
            return value

        monkeypatch.setattr(admission, "verify", synchronized)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(process, case, pending[0]) for _ in range(2)]
            values = [future.result(timeout=40) for future in futures]
        assert values[0] == values[1] and values[0]["state"] == "accepted"
        assert counts(case)["native_runs"] == counts(case)["tasks"] == 1

    def test_pending_cancel_replay_and_native_cancel_use_separate_exact_targets(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        automatic(case)
        _, pending = material_event(case)
        path = f"/api/v1/bids/{case['scope'][0]}/task-package-trigger-intents/{pending[0]['intent_id']}"
        observed = case["w"]["client"].get(path)
        export_http("cancel-pending", observed)
        request_headers = headers(case["w"], etag=observed.headers["etag"])
        baseline = len(case["f"]["calls"])
        response = case["w"]["client"].post(
            path + "/cancel",
            json={"reason": "Synthetic explicit pending cancel"},
            headers=request_headers,
        )
        assert response.status_code == 200 and response.json()["state"] == "cancelled", (
            response.text
        )
        export_http("cancelled", response)
        assert (
            case["w"]["client"]
            .post(
                path + "/cancel",
                json={"reason": "Synthetic explicit pending cancel"},
                headers=request_headers,
            )
            .json()
            == response.json()
        )
        assert process(case, pending[0]) == response.json() and len(case["f"]["calls"]) == baseline
        _, second = material_event(case)
        accepted = process(case, second[0])
        queued = task(case, accepted)
        native = (
            case["w"]["client"].get(queued["frozen_manifest"]["package_review"]["run_ref"]).json()
        )
        calls = self.provider(case, monkeypatch)
        self.cancel(case, native)
        engine.handle_lane("review", self.message(case, native))
        engine.reconcile(once=True)
        assert not calls and task(case, accepted)["state"] == "cancelled"

    def test_unknown_cost_blocks_new_event_but_preserves_original_intent_ack(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        automatic(case)
        _, pending = material_event(case)
        accepted = process(case, pending[0])
        queued = task(case, accepted)
        native = (
            case["w"]["client"].get(queued["frozen_manifest"]["package_review"]["run_ref"]).json()
        )
        calls = []

        def uncertain(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic acknowledgement unknown", request=request)

        client = DeepSeekClient(
            api_key="explicit-synthetic-no-network", transport=httpx.MockTransport(uncertain)
        )
        monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: client))
        message = self.message(case, native)
        engine.handle_lane("review", message)
        engine.handle_lane("review", message)
        assert len(calls) == 1 and task(case, accepted)["state"] == "reconciliation_required"
        _, second = material_event(case)
        blocked = process(case, second[0])
        assert (
            blocked["state"] == "blocked"
            and blocked["error_code"] == "MODEL_CALL_REQUIRES_RECONCILIATION"
        )
        assert process(case, pending[0]) == accepted and counts(case)["native_runs"] == 1

    def test_native_binding_guard_rejects_forged_ack_without_dropping_pending_intent(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        automatic(case)
        _, pending = material_event(case)
        publish = package_runs._publish

        def corrupt(c, **kwargs):
            result = publish(c, **kwargs)
            c.execute(
                "UPDATE commands SET response=jsonb_set(response,'{body,frozen_manifest,trigger_intent_id}',%s) WHERE command_kind='task-package-trigger-run' AND target_id=%s",
                (Jsonb(str(uuid4())), kwargs["intent"]["id"]),
            )
            return result

        monkeypatch.setattr(package_runs, "_publish", corrupt)
        with pytest.raises(psycopg.IntegrityError):
            process(case, pending[0])
        assert counts(case)["native_runs"] == counts(case)["tasks"] == 0
        with connection() as c:
            assert (
                package_triggers.view(
                    package_triggers.load(c, case["scope"][0], pending[0]["intent_id"])
                )["state"]
                == "pending"
            )

    def test_independent_runner_recovers_closed_pending_intent_and_no_provider_calls(
        self, launch_case
    ):
        case = launch_case
        automatic(case)
        _, pending = material_event(case)
        owner = case["w"]["database"]["owner"]
        owner.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        value = runner.cycle(after=UUID(int=UUID(case["scope"][0]).int - 1), limit=1)
        assert value["provider_calls"] == 0
        with connection() as c:
            observed = package_triggers.view(
                package_triggers.load(c, case["scope"][0], pending[0]["intent_id"])
            )
        assert observed["state"] == "blocked" and observed["error_code"] == "PROJECT_WORK_CLOSED"
        assert counts(case)["native_runs"] == 0

    def test_closed_project_recovers_existing_native_terminal_notification(self, launch_case):
        case = launch_case
        automatic(case)
        _, pending = material_event(case)
        accepted = process(case, pending[0])
        queued = task(case, accepted)
        native = (
            case["w"]["client"].get(queued["frozen_manifest"]["package_review"]["run_ref"]).json()
        )
        message = self.message(case, native)
        lease = engine.acquire(message)
        assert lease is not None
        engine.finish(message, lease, None, DomainError("SYNTHETIC_TASK_FAILURE", "合成故障"))
        owner = case["w"]["database"]["owner"]
        owner.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        before = counts(case)
        baseline = len(case["f"]["calls"])
        after = UUID(int=UUID(case["scope"][0]).int - 1)
        assert runner.cycle(after=after, limit=1)["provider_calls"] == 0
        assert runner.cycle(after=after, limit=1)["provider_calls"] == 0
        response = case["w"]["client"].get(f"/api/v1/bids/{case['scope'][0]}/task-notifications")
        matching = [r for r in response.json()["items"] if r["payload"]["run_id"] == queued["id"]]
        assert len(matching) == 1 and matching[0]["payload"]["state"] == "failed"
        assert len(case["f"]["calls"]) == baseline and counts(case) == before

    def test_roles_cannot_rewrite_or_publish_intents_and_manual_mode_stays_manual(
        self, launch_case
    ):
        case = launch_case
        template = create_template(case)
        _, values = material_event(case)
        assert values == [] and counts(case)["native_runs"] == 0
        with connection() as c:
            for privilege in ("UPDATE", "DELETE"):
                assert not c.execute(
                    "SELECT has_table_privilege(current_user,'design.task_package_trigger_intents',%s) AS p",
                    (privilege,),
                ).fetchone()["p"]
        with psycopg.connect(case["w"]["database"]["worker_dsn"]) as worker:
            assert not worker.execute(
                "SELECT has_table_privilege(current_user,'design.task_package_trigger_intents','INSERT')"
            ).fetchone()[0]
        assert template.json()["configuration"]["trigger"]["mode"] == "manual"
