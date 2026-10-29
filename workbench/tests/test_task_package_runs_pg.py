"""Exact manual tasks over real API/Worker roles and synthetic originals/model HTTP."""
# ruff: noqa: F401,F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from uuid import UUID

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_bid_package_requirements_api import database as base_database
from test_package_review_runs_api import TestPackageReviewRuns as _NativeCases
from test_package_review_runs_api import api, headers, requirements, uid, world

from apps.api.views import bid_etag
from apps.worker import engine
from packages.domain import bid_package_scope_review as admission
from packages.domain import storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import Command, DomainError, connection
from packages.tasks import coordinator, package_inputs, runs
from packages.tasks.models import RunPage, RunView, TaskKindPage, TemplateView

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner exact package task PG17 required",
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def database():
    source = base_database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        if (
            owner.execute(
                "SELECT to_regclass('design.task_package_review_bindings') AS name"
            ).fetchone()["name"]
            is None
        ):
            owner.execute((ROOT / "packages/contracts/sql/task-package-reviews.sql").read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def selected(case):
    capability = case["w"]["client"].get("/api/v1/task-kinds")
    assert capability.status_code == 200, capability.text
    TaskKindPage.model_validate(capability.json())
    method = next(row for row in capability.json()["items"] if row["task_kind"] == "denial_check")[
        "exact_package_manual"
    ]
    assert method["available"] is True and method["trigger"] == "manual"
    return {
        **dict(zip(("package_id", "revision_id", "inventory_id"), case["scope"][1:], strict=True)),
        "frozen_input_id": case["frozen"]["manifest"]["id"],
        "frozen_input_digest": case["frozen"]["digest"],
        "execution_input_id": case["prepared"]["manifest"]["id"],
        "execution_input_digest": case["prepared"]["digest"],
        "dependency_plan_id": case["plan"]["manifest"]["id"],
        "dependency_plan_digest": case["plan"]["digest"],
        "method_digest": method["method_digest"],
    }


def create_template(case, *, configuration=None):
    w = case["w"]
    body = configuration or {
        "name": "Synthetic exact package manual task",
        "task_kind": "denial_check",
        "instructions": "仅对明确所选整包和冻结要求进行范围核对；不确认或提交",
        "source_selection": {"mode": "exact_package_review", "input": selected(case)},
    }
    with connection() as c:
        tag = bid_etag(c, case["scope"][0])
    response = w["client"].post(
        f"/api/v1/bids/{case['scope'][0]}/task-definitions",
        json=body,
        headers=headers(w, etag=tag),
    )
    assert response.status_code == 201, response.text
    TemplateView.model_validate(response.json())
    return response


def launch(case, template, *, request_headers=None, body=None):
    return case["w"]["client"].post(
        f"/api/v1/bids/{case['scope'][0]}/task-definitions/{template.json()['id']}/runs",
        json={"rerun": False} if body is None else body,
        headers=request_headers or headers(case["w"], etag=template.headers["etag"]),
    )


def current(case, task):
    response = case["w"]["client"].get(f"/api/v1/bids/{case['scope'][0]}/task-runs/{task['id']}")
    assert response.status_code == 200, response.text
    RunView.model_validate(response.json())
    return response.json()


def counts(case):
    bid = case["scope"][0]
    return (
        case["w"]["database"]["owner"]
        .execute(
            """SELECT
        (SELECT count(*) FROM design.task_runs WHERE bid_id=%s) AS tasks,
        (SELECT count(*) FROM design.task_package_review_bindings WHERE bid_id=%s) AS bindings,
        (SELECT count(*) FROM design.bid_package_review_runs WHERE bid_id=%s) AS native_runs,
        (SELECT count(*) FROM design.operations WHERE bid_id=%s AND kind='package-scope-review') AS jobs,
        (SELECT count(*) FROM design.outbox x JOIN design.operations o ON o.id=x.operation_id
          WHERE o.bid_id=%s AND o.kind='package-scope-review') AS messages,
        (SELECT count(*) FROM design.commands WHERE actor_id=%s AND command_kind IN('task-run-manual','package-scope-review-start')) AS commands""",
            (bid, bid, bid, bid, bid, case["w"]["actor"]),
        )
        .fetchone()
    )


def export_ui_fixture(case, created, queued, original_headers):
    """Optional actual HTTP evidence for UI checks; strips all session/CSRF headers."""
    destination = os.environ.get("FUSION_TASK_PACKAGE_UI_EXPORT")
    if not destination:
        return
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    w, client = case["w"], case["w"]["client"]
    template, task = created.json(), queued.json()
    prefix = f"/api/v1/bids/{case['scope'][0]}"
    template_path = prefix + "/task-definitions/" + template["id"]
    prepared_path = case["path"].rsplit("/", 1)[0]
    frozen_path = prepared_path.split("/execution-inputs/", 1)[0]
    revision_path = f"{prefix}/packages/{case['scope'][1]}/revisions/{case['scope'][2]}"
    records = {}

    def save(name, response, expected=200):
        assert response.status_code == expected, response.text
        headers_kept = {
            key: response.headers[key]
            for key in ("etag", "task-run-reused", "idempotent-replayed", "content-type")
            if key in response.headers
        }
        command = {"method": response.request.method, "path": response.request.url.path}
        if response.request.method != "GET":
            command["body"] = json.loads(response.request.content)
            command["headers"] = {
                key: response.request.headers[key]
                for key in ("idempotency-key", "if-match")
                if key in response.request.headers
            }
        value = {
            "request": command,
            "status": response.status_code,
            "headers": headers_kept,
            "data": response.json(),
        }
        records[name] = value
        (root / (name + ".json")).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return value["data"]

    save("task-kinds", client.get("/api/v1/task-kinds"))
    save("package", client.get(revision_path))
    save("inventory", client.get(revision_path + "/requirement-inventories/" + case["scope"][3]))
    save("frozen-input", client.get(frozen_path))
    save("prepared-input", client.get(prepared_path))
    save(
        "dependency-plan",
        client.get(prepared_path + "/dependency-plans/" + case["plan"]["manifest"]["id"]),
    )
    save("template-created", created, 201)
    save(
        "template-version-created",
        client.get(template_path + "/versions/" + template["version_id"]),
    )
    save("run-queued-ack", queued, 202)
    save("run-completed", client.get(prefix + "/task-runs/" + task["id"]))
    save("native-run-completed", client.get(task["frozen_manifest"]["package_review"]["run_ref"]))
    save("operation-completed", client.get("/api/v1/operations/" + task["root_operation_id"]))
    revised = save(
        "template-revised",
        client.put(
            template_path,
            json=template["configuration"] | {"name": "Synthetic revised exact package task"},
            headers=headers(w, etag=created.headers["etag"]),
        ),
        200,
    )
    save(
        "template-version-revised", client.get(template_path + "/versions/" + revised["version_id"])
    )
    save("run-original-ack-replay", launch(case, created, request_headers=original_headers), 202)
    save("task-templates-page", client.get(prefix + "/task-definitions"))
    save("task-runs-page", client.get(prefix + "/task-runs"))
    save("task-notifications", client.get(prefix + "/task-notifications"))
    index = {
        "schema": "synthetic-task-package-ui-fixture/1",
        "synthetic": True,
        "source": "Actual HTTP responses from isolated PG17 API/Worker roles; in-memory synthetic originals and MockTransport provider, no paid call or production data.",
        "scope": dict(zip(package_inputs.SCOPE_KEYS, case["scope"], strict=True)),
        "selected_input": template["configuration"]["source_selection"]["input"],
        "files": sorted(name + ".json" for name in records),
        "credentials_included": False,
    }
    (root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestExactPackageTasks:
    original_case = _NativeCases.original_case
    frozen_case = _NativeCases.frozen_case
    execution_case = _NativeCases.execution_case
    prepared_case = _NativeCases.prepared_case
    exact_inventory_proof_case = _NativeCases.exact_inventory_proof_case
    launch_case = _NativeCases.launch_case
    post = _NativeCases.post
    message = _NativeCases.message
    provider = _NativeCases.provider
    cancel = _NativeCases.cancel
    equivalent_case = _NativeCases.equivalent_case

    def test_actual_template_task_worker_result_notification_and_original_ack(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        w = case["w"]
        baseline = len(case["f"]["calls"])
        created = create_template(case)
        assert len(case["f"]["calls"]) == baseline
        assert counts(case) == {
            "tasks": 0,
            "bindings": 0,
            "native_runs": 0,
            "jobs": 0,
            "messages": 0,
            "commands": 0,
        }
        assert created.json()["configuration"]["trigger"]["mode"] == "manual"
        request_headers = headers(w, etag=created.headers["etag"])
        response = launch(case, created, request_headers=request_headers)
        assert response.status_code == 202, response.text
        initial = response.json()
        RunView.model_validate(initial)
        assert initial["state"] == "queued" and initial["stage"] == "review"
        assert initial["root_operation_id"] == initial["final_operation_id"]
        assert initial["result"] is None and initial["formal_decisions_created"] is False
        assert initial["frozen_manifest"]["context"]["subject"]["kind"] == "bid_package"
        assert "body_version_id" not in initial["frozen_manifest"]["context"]
        assert counts(case) == {
            "tasks": 1,
            "bindings": 1,
            "native_runs": 1,
            "jobs": 1,
            "messages": 1,
            "commands": 2,
        }
        native = w["client"].get(initial["frozen_manifest"]["package_review"]["run_ref"]).json()
        calls = self.provider(case, monkeypatch)
        message = self.message(case, native)
        engine.handle_lane("review", message)
        finished = current(case, initial)
        assert finished["state"] == "succeeded", finished
        assert finished["result"]["overall_coverage"] == "partial"
        assert (
            finished["result"]["formal_scoring_eligible"]
            is finished["result"]["submission_eligible"]
            is False
        )
        assert len(calls) == 1
        engine.handle_lane("review", message)
        assert len(calls) == 1
        with connection() as c:
            row = c.execute("SELECT * FROM task_runs WHERE id=%s", (initial["id"],)).fetchone()
            assert runs.billing_operations(c, row) == [UUID(native["operation"]["id"])]
            stream = c.execute(
                "SELECT id,last_seq FROM stream_heads WHERE bid_id=%s", (case["scope"][0],)
            ).fetchone()
            assert (
                coordinator.reconcile_notifications(c, bid=UUID(case["scope"][0]))["created"] == 1
            )
            assert (
                coordinator.reconcile_notifications(c, bid=UUID(case["scope"][0]))["created"] == 0
            )
        notified = w["client"].get(f"/api/v1/bids/{case['scope'][0]}/task-notifications").json()
        assert len(notified["items"]) == 1
        assert notified["items"][0]["payload"]["run_id"] == initial["id"]
        from apps.api import event_routes

        monkeypatch.setattr(event_routes, "CONNECTION_SECONDS", 0.02)
        monkeypatch.setattr(event_routes, "POLL_SECONDS", 0.001)
        sse = w["client"].get(
            f"/api/v1/streams/{stream['id']}/events",
            headers={"Last-Event-ID": f"{stream['id']}:{stream['last_seq']}"},
        )
        assert sse.status_code == 200, sse.text
        changes = [
            json.loads(line[6:]) for line in sse.text.splitlines() if line.startswith("data: ")
        ]
        assert len(changes) == 1 and changes[0]["event_type"] == "task.notification"
        assert "frozen_manifest" not in sse.text and "instructions" not in sse.text
        page = w["client"].get(f"/api/v1/bids/{case['scope'][0]}/task-runs").json()
        RunPage.model_validate(page)
        assert page["items"] == [finished]
        before = counts(case)
        monkeypatch.setattr(
            storage, "client", lambda: pytest.fail("Original ACK must not re-admit originals")
        )
        recovered = launch(case, created, request_headers=request_headers)
        assert recovered.status_code == 202 and recovered.json() == initial
        assert recovered.headers["idempotent-replayed"] == "true"
        assert counts(case) == before
        assert current(case, initial) == finished
        export_ui_fixture(case, created, response, request_headers)

    def test_explicit_natural_language_draft_and_save_do_not_execute_or_read_originals(
        self, launch_case
    ):
        case = launch_case
        selection = {"mode": "exact_package_review", "input": selected(case)}
        with connection() as c:
            tag = bid_etag(c, case["scope"][0])
        path = f"/api/v1/bids/{case['scope'][0]}/task-definition-drafts"
        baseline = len(case["f"]["calls"])
        before = counts(case)
        draft = case["w"]["client"].post(
            path,
            json={"request": "核对所选附件的否决项", "source_selection": selection},
            headers=headers(case["w"], etag=tag),
        )
        assert draft.status_code == 201, draft.text
        value = draft.json()
        assert value["interpretation"]["source_selection"] == selection
        assert value["interpretation"]["ready_for_template_form"] is True
        loaded = case["w"]["client"].get(path + "/" + value["id"])
        assert loaded.status_code == 200 and loaded.json() == value
        saved = case["w"]["client"].post(
            path + "/" + value["id"] + "/save",
            json={},
            headers=headers(case["w"], etag=draft.headers["etag"]),
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["configuration"]["source_selection"] == selection
        assert saved.json()["run_created"] is False
        assert counts(case) == before and len(case["f"]["calls"]) == baseline

    def test_binding_grants_remain_api_append_only_and_unavailable_to_worker(self, launch_case):
        owner = launch_case["w"]["database"]["owner"]
        row = owner.execute("""SELECT
            has_table_privilege('fusion_package_requirements_service','design.task_package_review_bindings','SELECT,INSERT') AS api_write,
            has_table_privilege('fusion_package_requirements_service','design.task_package_review_bindings','UPDATE,DELETE') AS api_rewrite,
            has_table_privilege('fusion_package_requirements_worker','design.task_package_review_bindings','SELECT,INSERT,UPDATE,DELETE') AS worker_access,
            has_function_privilege('fusion_package_requirements_worker','design.task_package_binding_guard()','EXECUTE') AS worker_guard""").fetchone()
        assert row == {
            "api_write": True,
            "api_rewrite": False,
            "worker_access": False,
            "worker_guard": False,
        }

    def test_other_template_reuses_completed_native_result_and_same_template_reuses_task(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        first_template = create_template(case)
        first = launch(case, first_template)
        assert first.status_code == 202, first.text
        native = (
            case["w"]["client"]
            .get(first.json()["frozen_manifest"]["package_review"]["run_ref"])
            .json()
        )
        calls = self.provider(case, monkeypatch)
        engine.handle_lane("review", self.message(case, native))
        again = launch(case, first_template)
        assert again.status_code == 202 and again.headers["Task-Run-Reused"] == "true", again.text
        assert again.json()["id"] == first.json()["id"] and again.json()["state"] == "succeeded"
        other = create_template(case)
        second = launch(case, other)
        assert second.status_code == 202, second.text
        assert second.json()["id"] != first.json()["id"]
        assert (
            second.json()["state"] == "succeeded"
            and second.json()["result"] == again.json()["result"]
        )
        assert second.json()["root_operation_id"] == first.json()["root_operation_id"]
        assert counts(case) == {
            "tasks": 2,
            "bindings": 2,
            "native_runs": 1,
            "jobs": 1,
            "messages": 1,
            "commands": 5,
        }
        assert len(calls) == 1

    def test_ack_survives_failure_withdrawal_template_pause_and_closed_project(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        template = create_template(case)
        h = headers(case["w"], etag=template.headers["etag"])
        first = launch(case, template, request_headers=h)
        assert first.status_code == 202, first.text
        task = first.json()
        native = (
            case["w"]["client"].get(task["frozen_manifest"]["package_review"]["run_ref"]).json()
        )
        message = self.message(case, native)
        lease = engine.acquire(message)
        assert lease is not None
        engine.finish(message, lease, None, DomainError("SYNTHETIC_TASK_FAILURE", "合成故障"))
        paused = case["w"]["client"].post(
            f"/api/v1/bids/{case['scope'][0]}/task-definitions/{template.json()['id']}/pause",
            json={"paused": True},
            headers=headers(case["w"], etag=template.headers["etag"]),
        )
        assert paused.status_code == 200, paused.text
        owner = case["w"]["database"]["owner"]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (case["w"]["sources"][0],),
        )
        owner.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        monkeypatch.setattr(storage, "client", lambda: pytest.fail("Recovery is historical only"))
        again = launch(case, template, request_headers=h)
        assert again.status_code == 202 and again.json() == task, again.text
        assert again.headers["idempotent-replayed"] == "true"
        assert current(case, task)["state"] == "failed"
        assert current(case, task)["error_code"] == "SYNTHETIC_TASK_FAILURE"
        conflicting = launch(case, template, request_headers=h, body={"rerun": True})
        assert (
            conflicting.status_code == 409 and conflicting.json()["code"] == "IDEMPOTENCY_CONFLICT"
        )
        fresh = launch(case, paused)
        assert fresh.status_code == 409 and fresh.json()["code"] == "TASK_TEMPLATE_PAUSED"

    @pytest.mark.parametrize("same_key", [True, False])
    def test_concurrent_manual_requests_never_duplicate_native_work(
        self, launch_case, monkeypatch, same_key
    ):
        case = launch_case
        template = create_template(case)
        phase = Barrier(2)
        verify = admission.verify

        def synchronized(observed):
            phase.wait(timeout=30)
            value = verify(observed)
            phase.wait(timeout=30)
            return value

        monkeypatch.setattr(admission, "verify", synchronized)
        first_headers = headers(case["w"], etag=template.headers["etag"])
        second_headers = (
            first_headers if same_key else headers(case["w"], etag=template.headers["etag"])
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(launch, case, template, request_headers=h)
                for h in (first_headers, second_headers)
            ]
            responses = [future.result(timeout=40) for future in futures]
        assert [response.status_code for response in responses] == [202, 202], [
            r.text for r in responses
        ]
        assert responses[0].json() == responses[1].json()
        totals = counts(case)
        assert totals == {
            "tasks": 1,
            "bindings": 1,
            "native_runs": 1,
            "jobs": 1,
            "messages": 1,
            "commands": 2 if same_key else 3,
        }

    @pytest.mark.parametrize("change", ["template", "source", "project", "session"])
    def test_changed_admission_during_unlocked_original_io_rolls_back_every_publication(
        self, launch_case, change
    ):
        case = launch_case
        template = create_template(case)
        owner = case["w"]["database"]["owner"]
        before = counts(case)

        def mutate():
            if change == "template":
                response = case["w"]["client"].put(
                    f"/api/v1/bids/{case['scope'][0]}/task-definitions/{template.json()['id']}",
                    json=template.json()["configuration"]
                    | {"name": "A newly confirmed template version"},
                    headers=headers(case["w"], etag=template.headers["etag"]),
                )
                assert response.status_code == 200, response.text
            elif change == "source":
                owner.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (case["w"]["sources"][0],),
                )
            elif change == "project":
                owner.execute(
                    "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                    (case["scope"][0],),
                )
            else:
                owner.execute(
                    "UPDATE design.sessions SET revoked_at=clock_timestamp() WHERE member_id=%s",
                    (case["w"]["actor"],),
                )

        case["f"]["state"]["during_read"] = mutate
        response = launch(case, template)
        assert response.status_code == {"session": 401, "template": 412}.get(change, 409), (
            response.text
        )
        assert counts(case) == before

    def test_corrupt_originals_and_implicit_rerun_never_create_work(self, launch_case):
        case = launch_case
        template = create_template(case)
        before = counts(case)
        forbidden = launch(case, template, body={"rerun": True})
        assert (
            forbidden.status_code == 409
            and forbidden.json()["code"] == "TASK_PACKAGE_REPREPARE_REQUIRED"
        )
        case["f"]["state"]["bytes"] = b"corrupt synthetic task original"
        rejected = launch(case, template)
        assert (
            rejected.status_code == 409 and rejected.json()["code"] == "ORIGINAL_BYTES_CORRUPTED"
        ), rejected.text
        assert counts(case) == before

    def test_unknown_model_cost_blocks_new_template_and_explicit_prepared_rerun(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        template = create_template(case)
        first_headers = headers(case["w"], etag=template.headers["etag"])
        first = launch(case, template, request_headers=first_headers)
        assert first.status_code == 202, first.text
        initial = first.json()
        native = (
            case["w"]["client"].get(initial["frozen_manifest"]["package_review"]["run_ref"]).json()
        )
        calls = []

        def uncertain(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic provider acknowledgement unknown", request=request)

        client = DeepSeekClient(
            api_key="explicit-synthetic-no-network", transport=httpx.MockTransport(uncertain)
        )
        monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: client))
        message = self.message(case, native)
        engine.handle_lane("review", message)
        assert len(calls) == 1
        assert current(case, initial)["state"] == "reconciliation_required"
        engine.handle_lane("review", message)
        assert len(calls) == 1
        other = create_template(case)
        before = counts(case)
        blocked = launch(case, other)
        assert (
            blocked.status_code == 409
            and blocked.json()["code"] == "MODEL_CALL_REQUIRES_RECONCILIATION"
        ), blocked.text
        explicit = self.equivalent_case(
            case,
            rerun={
                "nonce": uid(),
                "reason": "Synthetic explicit recheck cannot authorize unknown charges",
            },
        )
        explicit_template = create_template(explicit)
        again = launch(explicit, explicit_template)
        assert (
            again.status_code == 409
            and again.json()["code"] == "MODEL_CALL_REQUIRES_RECONCILIATION"
        ), again.text
        recovered = launch(case, template, request_headers=first_headers)
        assert recovered.status_code == 202 and recovered.json() == initial
        assert counts(case) == before and len(calls) == 1

    def test_cancel_uses_the_real_native_operation_and_never_calls_provider(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        template = create_template(case)
        first = launch(case, template)
        assert first.status_code == 202, first.text
        native = (
            case["w"]["client"]
            .get(first.json()["frozen_manifest"]["package_review"]["run_ref"])
            .json()
        )
        calls = self.provider(case, monkeypatch)
        self.cancel(case, native)
        engine.handle_lane("review", self.message(case, native))
        engine.reconcile(once=True)
        value = current(case, first.json())
        assert value["state"] == "cancelled" and value["result"] is None
        assert calls == []

    @pytest.mark.parametrize("binding_source", ["both", "template", "operation"])
    def test_api_role_cannot_hide_exact_template_or_native_operation_behind_legacy_manifest(
        self, launch_case, binding_source
    ):
        case = launch_case
        exact = create_template(case)
        legacy = create_template(
            case,
            configuration={
                "name": "Legacy registered relation check",
                "task_kind": "supplement_impact",
                "instructions": "Keep its old bounded semantics",
            },
        )
        native_response = _NativeCases.launch(self, case)
        assert native_response.status_code == 202, native_response.text
        native = native_response.json()
        template = legacy if binding_source == "operation" else exact
        operation = native["operation"]["id"]
        if binding_source == "template":
            operation = (
                case["w"]["database"]["owner"]
                .execute(
                    "SELECT id FROM design.operations WHERE bid_id=%s AND kind='prepare-review' ORDER BY id LIMIT 1",
                    (case["scope"][0],),
                )
                .fetchone()["id"]
            )
        before = counts(case)
        with pytest.raises(psycopg.errors.CheckViolation, match="task_package_binding_parent"):
            with connection() as c:
                assert (
                    c.execute("SELECT current_user AS name").fetchone()["name"]
                    == "fusion_package_requirements_service"
                )
                c.execute(
                    "INSERT INTO task_runs(id,bid_id,definition_version_id,operation_id,frozen_manifest) VALUES(%s,%s,%s,%s,%s)",
                    (
                        uid(),
                        case["scope"][0],
                        template.json()["version_id"],
                        operation,
                        Jsonb(
                            {
                                "schema": "task-run/1",
                                "configuration": {
                                    "source_selection": {
                                        "mode": "current_project",
                                        "version_ids": [],
                                    }
                                },
                            }
                        ),
                    ),
                )
        assert counts(case) == before

    @pytest.mark.parametrize(
        "tamper",
        ["parent_state", "parent_result", "parent_error", "child_method", "child_prepared"],
    )
    def test_deferred_guard_rejects_forged_parent_and_child_ack_atomically(
        self, launch_case, monkeypatch, tamper
    ):
        case = launch_case
        template = create_template(case)
        native = _NativeCases.launch(self, case)
        assert native.status_code == 202, native.text
        before = counts(case)
        finish = Command.finish

        def corrupted(command, body, status=200, headers=None):
            value = deepcopy(body)
            if value.get("frozen_manifest", {}).get("schema") == package_inputs.SCHEMA:
                if tamper == "parent_state":
                    value["state"] = "succeeded"
                elif tamper == "parent_result":
                    value["result"] = {"formal_scoring_eligible": True, "invented": "success"}
                elif tamper == "parent_error":
                    value["error_code"] = "INVENTED_FAILURE"
                else:
                    field = (
                        "method_digest" if tamper == "child_method" else "execution_input_digest"
                    )
                    command.c.execute(
                        "UPDATE design.commands SET response=jsonb_set(response,%s,%s) WHERE id=%s",
                        (
                            ["body", field],
                            Jsonb("0" * 64),
                            value["frozen_manifest"]["package_review"]["start_command_id"],
                        ),
                    )
            return finish(command, value, status, headers)

        monkeypatch.setattr(Command, "finish", corrupted)
        response = launch(case, template)
        assert (
            response.status_code == 409
            and response.json()["code"] == "TASK_PACKAGE_STORAGE_REJECTED"
        ), response.text
        assert counts(case) == before

    def test_legacy_manual_path_remains_usable_and_package_trigger_bypass_is_blocked(
        self, launch_case
    ):
        case = launch_case
        legacy = create_template(
            case,
            configuration={
                "name": "Existing registered relation check",
                "task_kind": "supplement_impact",
                "instructions": "No invented full semantic coverage",
            },
        )
        response = launch(case, legacy)
        assert response.status_code == 202, response.text
        assert response.json()["state"] == "succeeded"
        assert response.json()["coverage"] == "registered_effectivity_only_semantic_unknown"
        exact = create_template(case)
        before = counts(case)
        with pytest.raises(DomainError) as error:
            with connection() as c:
                runs.dispatch(
                    c,
                    bid=case["scope"][0],
                    definition=exact.json()["id"],
                    actor=case["w"]["actor"],
                    command=uid(),
                    trigger="schedule",
                )
        assert error.value.code == "TASK_PACKAGE_EXPLICIT_COORDINATOR_REQUIRED"
        assert counts(case) == before
