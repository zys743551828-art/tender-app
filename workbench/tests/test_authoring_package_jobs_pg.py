"""Native fixed package authoring B2; synthetic originals/model, real PG17/S3."""
# ruff: noqa: F401,F811

import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID, uuid4

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, exact, saved, world
from authoring_package_job_fixtures import (
    bind_task,
    cancel,
    case,
    change_template,
    current,
    database,
    export,
    finish,
    input_database,
    launch,
    legacy_queue,
    no_action,
    no_job,
    queued,
    validate_wire,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_authoring_package_inputs_pg import add_new_parse, mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers

from apps.worker import engine
from packages.assistant import coordinator
from packages.domain.runtime import Command, DomainError, connection, sha
from packages.tasks import runs

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B2 PG17 and real S3")


def test_native_complete_fixed_inputs_publish_one_candidate_without_apply(queued):
    w = queued
    assert current(w)["state"] == "queued"
    validate_wire(w)
    export(w, "queued")
    engine.handle(w["message"])
    engine.handle(w["message"])
    assert len(w["calls"]) == 1
    pending = current(w)
    assert pending["state"] == "awaiting_publication", pending
    assert pending["result"]["source_scope"] == "exact_package_context"
    assert pending["result"]["action_id"] is None
    validate_wire(w)
    export(w, "awaiting-publication")
    with connection() as c:
        assert not runs.notify(c, UUID(w["bid"]), UUID(w["task"]["id"]))
    coordinator.tick([w["job_id"]])
    coordinator.tick([w["job_id"]])
    ready = current(w)
    assert ready["state"] == "succeeded", ready
    assert ready["result"]["publication_state"] == "published"
    assert ready["result"]["apply_available"] is False
    action = w["client"].get(ready["result"]["action_ref"])
    assert action.status_code == 200, action.text
    assert action.json()["preview"]["source_scope"] == "exact_package_context"
    assert action.json()["preview"]["before"] != action.json()["preview"]["after"]
    rejected = w["client"].post(
        ready["result"]["action_ref"] + "/resolve",
        json={"decision": "confirm"},
        headers=headers(w, etag=action.headers["etag"]),
    )
    assert (
        rejected.status_code == 409
        and rejected.json()["code"] == "AUTHORING_PACKAGE_APPLY_NOT_CONFIGURED"
    )
    with connection() as c:
        assert runs.notify(c, UUID(w["bid"]), UUID(w["task"]["id"]))
        assert not runs.notify(c, UUID(w["bid"]), UUID(w["task"]["id"]))
        assert (
            c.execute(
                "SELECT revision FROM design.drafts WHERE id=%s",
                (w["input_body"]["target_section"]["draft_id"],),
            ).fetchone()["revision"]
            == 1
        )
    assert len(w["calls"]) == 1
    validate_wire(w)
    export(w, "published")


@pytest.mark.parametrize("terminal", ["published", "unknown_fee", "cancelled"])
def test_lost_ack_replays_original_acceptance_separately_from_current_state(queued, terminal):
    w = queued
    original = deepcopy(w["task"])
    if terminal == "unknown_fee":
        w["mode"] = "timeout"
    elif terminal == "cancelled":
        cancel(w)
    live = finish(w)
    if terminal == "cancelled":
        engine.reconcile(once=True)
        live = current(w)
    assert (
        live["state"]
        == {
            "published": "succeeded",
            "unknown_fee": "reconciliation_required",
            "cancelled": "cancelled",
        }[terminal]
    )
    calls = len(w["calls"])
    recovered = launch(w, key=w["key"])
    assert recovered.status_code == 202, recovered.text
    assert recovered.headers["Task-Run-Reused"] == "false"
    assert recovered.json() == original
    assert recovered.json()["state"] == "queued"
    assert current(w) == live
    assert len(w["calls"]) == calls


def test_original_and_reused_saved_ack_cannot_be_modified(queued):
    w = queued
    assert finish(w)["state"] == "succeeded"
    reuse_key = uuid4().hex
    reused = launch(w, key=reuse_key)
    assert reused.status_code == 202 and reused.json()["state"] == "succeeded"
    assert reused.headers["Task-Run-Reused"] == "true"
    for key in (w["key"], reuse_key):
        with pytest.raises(
            psycopg.errors.CheckViolation, match="AUTHORING_PACKAGE_RECEIPT_IMMUTABLE"
        ):
            with connection() as c:
                c.execute(
                    "UPDATE design.commands SET response=jsonb_set(response,'{body,result,authoring_input_digest}',to_jsonb(%s::text)) "
                    "WHERE actor_id=%s AND command_kind='task-package-authoring-run' AND idempotency_key=%s",
                    ("0" * 64, w["actor"], key),
                )
    assert launch(w, key=w["key"]).json() == w["task"]
    assert launch(w, key=reuse_key).json() == reused.json()
    assert len(w["calls"]) == 1


def test_nonowner_roles_and_narrow_executor_grants(case):
    w = case
    for kind in ("api", "worker"):
        with psycopg.connect(w["database"][kind + "_dsn"], row_factory=dict_row) as c:
            role = c.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert role == {"rolsuper": False, "rolbypassrls": False}
            for table in ("authoring_package_job_bindings", "authoring_package_action_bindings"):
                rights = c.execute(
                    "SELECT has_table_privilege(current_user,%s,'SELECT') AS r,has_table_privilege(current_user,%s,'INSERT') AS i,has_table_privilege(current_user,%s,'UPDATE') AS u,has_table_privilege(current_user,%s,'DELETE') AS d",
                    ("design." + table,) * 4,
                ).fetchone()
                assert rights == {"r": kind == "api", "i": kind == "api", "u": False, "d": False}
            rights = c.execute(
                "SELECT has_function_privilege(current_user,'design.authoring_package_assert_job(uuid)','EXECUTE') AS public_rpc,has_function_privilege(current_user,'design.authoring_package_assert_input(uuid)','EXECUTE') AS internal"
            ).fetchone()
            assert rights == {"public_rpc": True, "internal": False}
    kinds = w["client"].get("/api/v1/task-kinds").json()["items"]
    capabilities = next(v for v in kinds if v["task_kind"] == "chapter_suggestion")[
        "exact_package_authoring"
    ]
    assert (
        capabilities["available"]
        and not capabilities["apply_available"]
        and not capabilities["build_available"]
    )


def test_fixed_old_parse_executes_without_any_legacy_latest_capture(case, monkeypatch):
    from packages.assistant import context, intent_identity
    from packages.authoring import generation
    from packages.tasks import inputs

    newer = add_new_parse(case)

    def forbidden(*args, **kwargs):
        raise AssertionError("exact task entered legacy latest-parse/current-fact capture")

    monkeypatch.setattr(inputs, "capture", forbidden)
    monkeypatch.setattr(generation, "freeze_generation_plan", forbidden)
    monkeypatch.setattr(intent_identity, "resolve", forbidden)
    monkeypatch.setattr(context, "project_memory", forbidden)
    monkeypatch.setattr(context, "assert_generation_context", forbidden)
    response = launch(case)
    assert response.status_code == 202, response.text
    bind_task(case, response.json())
    assert finish(case)["state"] == "succeeded"
    request = case["calls"][0]
    submitted = str(request)
    assert newer not in submitted
    assert str(case["member"].parse.parse_run_id) in submitted
    assert "complete_fixed_package_plan" in submitted
    assert "object_key" not in submitted
    assert len(case["calls"]) == 1


def test_replay_survives_lost_original_and_conflicting_key_does_not_mutate(queued):
    from packages.domain import storage

    w = queued
    storage.client().delete_object(Bucket=storage.bucket(), Key=w["blob"]["object_key"])
    repeated = launch(w, key=w["key"])
    assert repeated.status_code == 202 and repeated.json()["id"] == w["task"]["id"]
    conflict = launch(w, key=w["key"], rerun=True)
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    fresh = launch(w)
    assert fresh.status_code == 409 and fresh.json()["code"] == "ORIGINAL_NOT_AVAILABLE"
    assert not w["calls"]


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_runs_reuse_original_native_job(case, same_key):
    keys = [uuid4().hex, uuid4().hex]
    if same_key:
        keys[1] = keys[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda key: launch(case, key=key), keys))
    assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.authoring_package_job_bindings WHERE bid_id=%s",
                (case["bid"],),
            ).fetchone()["n"]
            == 1
        )
    assert not case["calls"]


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_change_during_original_io_rejects_acceptance_without_job(case, monkeypatch, change):
    from packages.domain import original_verification

    original = original_verification.verify
    changed = False

    def mutate(document):
        nonlocal changed
        original(document)
        if not changed:
            changed = True
            mutate_authority(case, change)

    monkeypatch.setattr(original_verification, "verify", mutate)
    response = launch(case)
    assert response.status_code == 409, response.text
    assert changed and not case["calls"]
    no_job(case)


@pytest.mark.parametrize("phase", ["before_dispatch", "before_publication"])
@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_current_authority_fences_native_dispatch_and_publication(queued, phase, change):
    w = queued
    if phase == "before_publication":
        assert finish(w, publish=False)["state"] == "awaiting_publication"
    mutate_authority(w, change)
    if phase == "before_dispatch":
        engine.handle(w["message"])
        engine.reconcile(once=True)
    coordinator.tick([w["job_id"]])
    result = current(w)
    assert result["state"] in (
        {"failed", "cancelled"} if phase == "before_dispatch" else {"superseded"}
    ), result
    assert result["result"]["action_id"] is None
    assert len(w["calls"]) == int(phase == "before_publication")
    no_action(w)
    with connection() as c:
        assert runs.notify(c, UUID(w["bid"]), UUID(w["task"]["id"]))
        assert not runs.notify(c, UUID(w["bid"]), UUID(w["task"]["id"]))


def test_fact_purpose_withdrawal_blocks_candidate_publication(queued):
    w = queued
    assert finish(w, publish=False)["state"] == "awaiting_publication"
    declaration = w["fixed"]["manifest"]["fact_declarations"][0]
    response = w["client"].post(
        w["input_base"] + "/" + w["fixed"]["manifest"]["id"] + "/fact-withdrawals",
        json={
            "input_digest": w["fixed"]["digest"],
            "fact_id": declaration["manifest"]["fact_id"],
            "declaration_digest": declaration["digest"],
            "reason": "合成固定用途声明撤回",
        },
        headers=headers(w),
    )
    assert response.status_code == 201, response.text
    coordinator.tick([w["job_id"]])
    value = current(w)
    assert value["state"] == "superseded" and value["result"]["publication_state"] == "stale", value
    no_action(w)


def test_template_pause_during_io_rejects_new_acceptance(case, monkeypatch):
    from packages.domain import original_verification

    verify = original_verification.verify
    changed = False

    def paused(document):
        nonlocal changed
        verify(document)
        if not changed:
            changed = True
            response = case["client"].post(
                f"/api/v1/bids/{case['bid']}/task-definitions/{case['template']['id']}/pause",
                json={"paused": True},
                headers=headers(case, etag=case["template_response"].headers["etag"]),
            )
            assert response.status_code == 200, response.text

    monkeypatch.setattr(original_verification, "verify", paused)
    response = launch(case)
    assert response.status_code in (409, 412), response.text
    no_job(case)


def test_accepted_job_keeps_original_template_and_no_automatic_trigger(queued):
    w = queued
    change_template(w, instructions="新的明确说明，不替换已接受的原请求")
    assert finish(w)["state"] == "succeeded"
    assert (
        current(w)["frozen_manifest"]["configuration"]["instructions"]
        != w["template"]["configuration"]["instructions"]
    )
    config = deepcopy(w["template"]["configuration"])
    config["trigger"] = {"mode": "material_updated", "timezone": "Asia/Shanghai"}
    response = w["client"].put(
        f"/api/v1/bids/{w['bid']}/task-definitions/{w['template']['id']}",
        json=config,
        headers=headers(w, etag=w["template_response"].headers["etag"]),
    )
    assert response.status_code == 422
    assert launch(w, rerun=True).status_code == 409


def test_final_session_revocation_does_not_leave_job(case):
    from packages.tasks import package_authoring_runs

    def revoked():
        raise DomainError("AUTH_REQUIRED", "synthetic final session revocation", 401)

    with pytest.raises(DomainError, match="synthetic final session revocation"):
        package_authoring_runs.start(
            UUID(case["actor"]),
            UUID(case["bid"]),
            UUID(case["template"]["id"]),
            uuid4().hex,
            case["template_response"].headers["etag"],
            {"rerun": False},
            final_auth=revoked,
        )
    no_job(case)


@pytest.mark.parametrize("automatic", [False, True])
def test_private_exact_draft_preserves_input_and_requires_explicit_manual_template_save(
    case, automatic
):
    from apps.api.views import bid_etag

    w = case
    base = f"/api/v1/bids/{w['bid']}/task-definition-drafts"
    config = deepcopy(w["template"]["configuration"])
    body = {
        "request": "每天8点用完整整包编写章节建议" if automatic else "用完整整包编写章节建议",
        "section_id": config["section_id"],
        "source_selection": config["source_selection"],
    }
    with connection() as c:
        condition = bid_etag(c, UUID(w["bid"]))
    key = uuid4().hex
    first = w["client"].post(base, json=body, headers=headers(w, key=key, etag=condition))
    assert first.status_code == 201, first.text
    original = first.json()
    assert original["interpretation"]["source_selection"] == config["source_selection"]
    assert original["interpretation"]["run_created"] is False
    replay = w["client"].post(base, json=body, headers=headers(w, key=key, etag=condition))
    assert replay.json() == original
    path = base + "/" + original["id"]
    assert w["client"].get(path).json() == original
    if automatic:
        assert original["interpretation"]["unresolved"]
        rejected = w["client"].post(
            path + "/save", json={}, headers=headers(w, etag=first.headers["etag"])
        )
        assert (
            rejected.status_code == 409
            and rejected.json()["code"] == "TASK_DRAFT_NEEDS_CLARIFICATION"
        ), rejected.text
        no_job(w)
        return
    edited_body = config | {"instructions": "按完整固定输入编写本章候选，保持原草稿"}
    edit_key = uuid4().hex
    edited = w["client"].put(
        path,
        json=edited_body,
        headers=headers(w, key=edit_key, etag=first.headers["etag"]),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["interpretation"]["source_selection"] == config["source_selection"]
    assert edited.json()["interpretation"]["raw_request"] == body["request"]
    edit_replay = w["client"].put(
        path, json=edited_body, headers=headers(w, key=edit_key, etag=first.headers["etag"])
    )
    assert edit_replay.json() == edited.json()
    no_job(w)
    key = uuid4().hex
    accepted = w["client"].post(
        path + "/save", json={}, headers=headers(w, key=key, etag=edited.headers["etag"])
    )
    assert accepted.status_code == 201, accepted.text
    save_replay = w["client"].post(
        path + "/save", json={}, headers=headers(w, key=key, etag=edited.headers["etag"])
    )
    assert save_replay.json() == accepted.json()
    final_draft = w["client"].get(path)
    assert final_draft.status_code == 200, final_draft.text
    w["task_draft_flow"] = {
        "created": {
            "request": body,
            "if_match": condition,
            "body": original,
            "status": first.status_code,
            "etag": first.headers["etag"],
            "replay_body": replay.json(),
        },
        "revised": {
            "request": edited_body,
            "if_match": first.headers["etag"],
            "body": edited.json(),
            "status": edited.status_code,
            "etag": edited.headers["etag"],
            "replay_body": edit_replay.json(),
        },
        "saved": {
            "request": {},
            "if_match": edited.headers["etag"],
            "body": accepted.json(),
            "status": accepted.status_code,
            "etag": accepted.headers["etag"],
            "replay_body": save_replay.json(),
        },
        "final": {
            "body": final_draft.json(),
            "status": final_draft.status_code,
            "etag": final_draft.headers["etag"],
        },
    }
    assert accepted.json()["configuration"]["source_selection"] == config["source_selection"]
    assert not accepted.json()["run_created"]
    no_job(w)
    w.update(template=accepted.json(), template_response=accepted, private_draft_id=original["id"])
    response = launch(w)
    assert response.status_code == 202, response.text
    bind_task(w, response.json())
    assert finish(w)["state"] == "succeeded"
    export(w, "private-draft-saved")


def test_private_draft_rejects_another_digest_without_latest_fallback(case):
    from apps.api.views import bid_etag

    selected = deepcopy(case["template"]["configuration"]["source_selection"])
    selected["input"]["authoring_input_digest"] = "0" * 64
    with connection() as c:
        condition = bid_etag(c, UUID(case["bid"]))
    response = case["client"].post(
        f"/api/v1/bids/{case['bid']}/task-definition-drafts",
        json={
            "request": "编写章节建议",
            "section_id": case["input_body"]["target_section"]["section_id"],
            "source_selection": selected,
        },
        headers=headers(case, etag=condition),
    )
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_PACKAGE_INPUT_BINDING_INVALID"
    ), response.text
    no_job(case)


def test_unknown_fee_reuses_original_and_blocks_new_template_input_and_legacy(queued):
    w = queued
    w["mode"] = "timeout"
    value = finish(w)
    assert value["state"] == "reconciliation_required", value
    same = launch(w)
    assert same.status_code == 202 and same.json()["id"] == value["id"]
    assert same.json()["state"] == "reconciliation_required"
    assert launch(w, rerun=True).status_code == 409
    other = saved(w)
    change_template(
        w,
        source_selection={
            "mode": "exact_package_authoring",
            "input": {
                "authoring_input_id": other["manifest"]["id"],
                "authoring_input_digest": other["digest"],
            },
        },
    )
    blocked = launch(w)
    assert (
        blocked.status_code == 409
        and blocked.json()["code"] == "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED"
    ), blocked.text
    change_template(w, instructions="在同一对象继续改写，不能因此获得独立费用许可")
    blocked = launch(w)
    assert (
        blocked.status_code == 409 and blocked.json()["code"] == "ASSISTANT_INDEPENDENCE_UNPROVEN"
    ), blocked.text
    with pytest.raises(DomainError) as caught:
        legacy_queue(w, instruction="同一章节的新文字说明，不能逃逸旧未决账本")
    assert caught.value.code == "ASSISTANT_INDEPENDENCE_UNPROVEN"
    assert len(w["calls"]) == 1
    no_action(w)
    export(w, "unknown-fee")


@pytest.mark.parametrize("terminal", ["unknown_fee", "settled"])
@pytest.mark.parametrize("change", ["new_revision", "new_template", "new_saved_input"])
def test_other_template_version_cannot_wrap_existing_native_job_as_new_acceptance(
    queued, change, terminal
):
    from apps.api.views import bid_etag

    w = queued
    w["mode"] = "timeout" if terminal == "unknown_fee" else "success"
    assert finish(w)["state"] == (
        "reconciliation_required" if terminal == "unknown_fee" else "succeeded"
    )
    if change == "new_revision":
        change_template(w, name="相同固定输入和指令的另一个模板版本")
    elif change == "new_template":
        config = deepcopy(w["template"]["configuration"])
        config["name"] = "另一个模板不能包装原运行"
        with connection() as c:
            condition = bid_etag(c, UUID(w["bid"]))
        response = w["client"].post(
            f"/api/v1/bids/{w['bid']}/task-definitions",
            json=config,
            headers=headers(w, etag=condition),
        )
        assert response.status_code == 201, response.text
        w.update(template=response.json(), template_response=response)
    else:
        duplicate = saved(w)
        assert duplicate["manifest"]["context_digest"] == w["fixed"]["manifest"]["context_digest"]
        change_template(
            w,
            source_selection={
                "mode": "exact_package_authoring",
                "input": {
                    "authoring_input_id": duplicate["manifest"]["id"],
                    "authoring_input_digest": duplicate["digest"],
                },
            },
        )
    new_key = uuid4().hex
    blocked = launch(w, key=new_key)
    assert (
        blocked.status_code == 409
        and blocked.json()["code"] == "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED"
    ), blocked.text
    assert blocked.json()["details"] == {
        "bid_id": w["bid"],
        "job_id": str(w["job_id"]),
        "task_run_id": w["task"]["id"],
        "new_attempt_authorized": False,
    }
    assert launch(w, key=new_key).json()["code"] == "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED"
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.commands WHERE actor_id=%s AND command_kind='task-package-authoring-run' AND idempotency_key=%s",
            (w["actor"], new_key),
        ).fetchone()
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.task_runs WHERE bid_id=%s", (w["bid"],)
            ).fetchone()["n"]
            == 1
        )
    assert len(w["calls"]) == 1


def test_sql_prevents_second_semantic_job_even_if_application_lookup_is_bypassed(
    queued, monkeypatch
):
    from packages.authoring import package_jobs

    w = queued
    assert finish(w)["state"] == "succeeded"
    change_template(w, name="合成：绕过Python查询仍不能产生第二个相同任务")
    monkeypatch.setattr(package_jobs, "prior_semantic", lambda *args: None)
    rejected = launch(w)
    assert rejected.status_code == 503 and rejected.json()["code"] == "DATABASE_TRANSACTION_FAILED"
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.authoring_package_job_bindings WHERE bid_id=%s",
                (w["bid"],),
            ).fetchone()["n"]
            == 1
        )
    assert len(w["calls"]) == 1


def test_settled_task_allows_explicitly_different_substantive_instruction(queued):
    w = queued
    assert finish(w)["state"] == "succeeded"
    old_id = w["task"]["id"]
    change_template(w, instructions="另一个明确目标：把该段改为逐项施工核验说明并保留证据")
    next_run = launch(w)
    assert next_run.status_code == 202, next_run.text
    assert next_run.json()["id"] != old_id
    bind_task(w, next_run.json())
    assert finish(w)["state"] == "succeeded"
    assert len(w["calls"]) == 2


def test_legacy_unknown_fee_blocks_exact_new_input(case):
    w = case
    w["mode"] = "timeout"
    legacy = legacy_queue(w)
    with connection() as c:
        message = c.execute(
            "SELECT payload FROM design.outbox WHERE operation_id=%s AND topic='tender.task.assistant.v1'",
            (legacy["operation"]["id"],),
        ).fetchone()["payload"]
    engine.handle(message)
    engine.handle(message)
    blocked = launch(w)
    assert (
        blocked.status_code == 409
        and blocked.json()["code"] == "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED"
    ), blocked.text
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.authoring_package_job_bindings WHERE bid_id=%s", (w["bid"],)
        ).fetchone()
    assert len(w["calls"]) == 1
    no_action(w)


@pytest.mark.parametrize("when", ["before", "during_http"])
def test_original_cancel_survives_duplicate_worker_and_late_http(queued, when):
    w = queued
    if when == "before":
        cancel(w)
    else:
        w["after_http"] = lambda: cancel(w)
    engine.handle(w["message"])
    engine.reconcile(once=True)
    engine.handle(w["message"])
    coordinator.tick([w["job_id"]])
    value = current(w)
    assert value["state"] == "cancelled", value
    assert value["result"]["action_id"] is None
    assert len(w["calls"]) == int(when == "during_http")
    no_action(w)
    export(w, "cancelled-" + when)


@pytest.mark.parametrize("attack", ["malformed", "wrong_node", "wrong_citation"])
def test_bad_model_result_is_failed_without_candidate_or_action(queued, attack):
    w = queued
    if attack == "malformed":
        w["mode"] = "malformed"
    elif attack == "wrong_node":
        w["raw"]["node_id"] = "different-stable-node"
    else:
        w["raw"]["evidence_ids"] = [str(uuid4())]
    value = finish(w)
    assert value["state"] == "failed" and value["result"]["candidate_digest"] is None, value
    assert len(w["calls"]) == 1
    no_action(w)


def test_publication_exception_rolls_back_proposal_and_binding(queued, monkeypatch):
    from packages.authoring import package_publication

    assert finish(queued, publish=False)["state"] == "awaiting_publication"
    create = package_publication.create

    def fail(c, job, output):
        create(c, job, output)
        raise DomainError("EXPLICIT_PACKAGE_PUBLICATION_FAILURE", "合成提案插入后回滚", 422)

    monkeypatch.setattr(package_publication, "create", fail)
    coordinator.tick([queued["job_id"]])
    value = current(queued)
    assert value["state"] == "failed" and value["result"]["publication_state"] == "failed", value
    no_action(queued)
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.authoring_package_action_bindings WHERE bid_id=%s",
            (queued["bid"],),
        ).fetchone()
    assert len(queued["calls"]) == 1


@pytest.mark.parametrize(
    "attack", ["partial_document", "invented_instruction", "wrong_context_digest", "fake_fact_use"]
)
def test_sql_rejects_rehashed_plan_that_does_not_equal_protected_input(case, monkeypatch, attack):
    from packages.authoring import package_generation

    original = package_generation.plan

    def forged(row, instruction, **kwargs):
        value = original(row, instruction, **kwargs)
        if attack == "partial_document":
            value["context"]["documents"][0]["blocks"].pop()
        elif attack == "invented_instruction":
            value["context"]["documents"][0]["blocks"][0]["text_content"] = "伪造完整输入文本"
        elif attack == "wrong_context_digest":
            value["input"]["context_digest"] = "0" * 64
        else:
            value["fact_declarations"] = []
        return value

    monkeypatch.setattr(package_generation, "plan", forged)
    response = launch(case)
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_PACKAGE_PLAN_BINDING_INVALID"
    ), response.text
    assert not case["calls"]
    no_job(case)


def test_sql_rejects_forged_original_ack(case, monkeypatch):
    original = Command.finish

    def forged(self, body, status=200, headers=None):
        altered = deepcopy(body)
        if (
            isinstance(altered, dict)
            and altered.get("frozen_manifest", {}).get("schema") == "task-package-authoring-run/1"
        ):
            altered["result"]["build_available"] = True
        return original(self, altered, status, headers)

    monkeypatch.setattr(Command, "finish", forged)
    response = launch(case)
    assert (
        response.status_code == 503 and response.json()["code"] == "DATABASE_TRANSACTION_FAILED"
    ), response.text
    no_job(case)


@pytest.mark.parametrize("gate", ["commit", "reserve"])
def test_fake_mode_without_protected_binding_cannot_commit_or_reserve(case, gate):
    from packages.domain.runtime import enqueue_plan

    w = case
    expected = (
        "AUTHORING_PACKAGE_JOB_BINDING_INVALID" if gate == "commit" else "ASSISTANT_INTENT_INVALID"
    )
    with pytest.raises(psycopg.errors.CheckViolation, match=expected):
        with connection() as c:
            command = Command(
                c, UUID(w["actor"]), "synthetic-fake-mode", UUID(w["bid"]), uuid4().hex, {}
            )
            identity, plan_id = uuid4(), uuid4()
            manifest = {
                "kind": "authoring",
                "generation_mode": "exact_package_authoring/1",
                "job_id": str(identity),
            }
            c.execute(
                "INSERT INTO design.writing_plans(id,bid_id,section_id,base_section_revision,rule_ids,source_version_ids,plan) VALUES(%s,%s,%s,1,%s,%s,%s)",
                (
                    plan_id,
                    w["bid"],
                    w["input_body"]["target_section"]["section_id"],
                    [],
                    [],
                    Jsonb({}),
                ),
            )
            operation = enqueue_plan(
                c,
                UUID(w["bid"]),
                command.id,
                "authoring-generate",
                {"id": str(identity), "digest": sha(manifest)},
                stages=[{"key": "authoring-generate", "depends_on": []}],
                handler_version="authoring-generate/1",
                topic="tender.task.assistant.v1",
            )
            c.execute(
                "INSERT INTO design.assistant_jobs(id,kind,scope,bid_id,writing_plan_id,operation_id,actor_id,input_manifest,input_digest,intent_digest) VALUES(%s,'authoring','project',%s,%s,%s,%s,%s,%s,%s)",
                (
                    identity,
                    w["bid"],
                    plan_id,
                    operation["id"],
                    w["actor"],
                    Jsonb(manifest),
                    sha(manifest),
                    "0" * 64,
                ),
            )
            if gate == "reserve":
                c.execute("SELECT design.assistant_reserve_budget(%s)", (identity,))
    no_job(w)


def test_method_change_blocks_dispatch_but_preserves_history(queued, monkeypatch):
    from packages.authoring import package_generation

    original = package_generation.policy
    monkeypatch.setattr(
        package_generation, "policy", lambda: original() | {"explicit_test_method_revision": 2}
    )
    assert current(queued)["state"] == "queued"
    engine.handle(queued["message"])
    value = current(queued)
    assert value["state"] == "failed", value
    assert not queued["calls"]
    no_action(queued)


def test_method_change_before_publication_keeps_candidate_readable_but_stale(queued, monkeypatch):
    from packages.authoring import package_generation

    assert finish(queued, publish=False)["state"] == "awaiting_publication"
    original = package_generation.policy
    monkeypatch.setattr(
        package_generation, "policy", lambda: original() | {"explicit_test_method_revision": 2}
    )
    coordinator.tick([queued["job_id"]])
    value = current(queued)
    assert (
        value["state"] == "superseded" and value["error_code"] == "AUTHORING_PACKAGE_METHOD_CHANGED"
    ), value
    assert value["result"]["candidate_digest"]
    no_action(queued)


def test_natural_source_expiry_blocks_publication_without_revision_change(case):
    from packages.knowledge.sources import lock_graph
    from packages.rag.indexing import original_source_id

    w = case
    with connection() as c:
        version = c.execute(
            "SELECT document_version_id FROM design.parse_runs WHERE id=(SELECT (manifest#>>'{members,0,parse,parse_run_id}')::uuid FROM design.bid_package_revisions WHERE id=%s)",
            (w["input_body"]["package_context"]["authority"]["revision_id"],),
        ).fetchone()["document_version_id"]
        source = original_source_id(version)
        lock_graph(c)
        revision = c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,valid_until=clock_timestamp()+interval '10 seconds' WHERE source_id=%s RETURNING revision",
            (source,),
        ).fetchone()["revision"]
    fresh = saved(w)
    w["fixed"] = fresh
    change_template(
        w,
        source_selection={
            "mode": "exact_package_authoring",
            "input": {
                "authoring_input_id": fresh["manifest"]["id"],
                "authoring_input_digest": fresh["digest"],
            },
        },
    )
    response = launch(w)
    assert response.status_code == 202, response.text
    bind_task(w, response.json())
    assert finish(w, publish=False)["state"] == "awaiting_publication"
    with connection() as c:
        remaining = c.execute(
            "SELECT greatest(0,extract(epoch FROM valid_until-clock_timestamp())) AS seconds FROM retrieval.source_heads WHERE source_id=%s",
            (source,),
        ).fetchone()["seconds"]
    time.sleep(float(remaining) + 0.02)
    coordinator.tick([w["job_id"]])
    result = current(w)
    assert result["state"] == "superseded" and result["result"]["publication_state"] == "stale", (
        result
    )
    with connection() as c:
        assert (
            c.execute(
                "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
            ).fetchone()["revision"]
            == revision
        )
    no_action(w)


def test_copied_proposal_payload_without_action_binding_cannot_commit(queued):
    assert finish(queued)["state"] == "succeeded"
    with pytest.raises(
        psycopg.errors.CheckViolation, match="AUTHORING_PACKAGE_ACTION_BINDING_INVALID"
    ):
        with connection() as c:
            c.execute(
                "INSERT INTO design.proposed_actions(id,bid_id,base_revision,request_digest,expires_at,payload) SELECT %s,bid_id,base_revision,request_digest,expires_at,payload FROM design.proposed_actions WHERE id=%s",
                (uuid4(), current(queued)["result"]["action_id"]),
            )
    assert len(queued["calls"]) == 1


def test_full_request_over_actual_price_input_limit_rolls_back_without_truncation(case):
    from packages.domain.runtime import now

    def tariff(ceiling):
        case["database"]["owner"].execute(
            "INSERT INTO design.assistant_price_versions(id,version,provider,model,currency,input_per_million_minor,output_per_million_minor,input_hard_ceiling,output_hard_ceiling,source_kind,source_uri,source_sha256,verified_at,valid_from,valid_until) VALUES(%s,%s,'deepseek','deepseek-flash','USD',1000000,1000000,%s,8192,'explicit_mock_fixture','https://synthetic.invalid/bounded-input',%s,%s,clock_timestamp()-interval '1 hour',clock_timestamp()+interval '4 hours')",
            (uuid4(), uuid4().hex, ceiling, sha(b"explicit bounded input fixture"), now()),
        )

    try:
        tariff(1000)
        response = launch(case)
        assert (
            response.status_code == 422 and response.json()["code"] == "ASSISTANT_INPUT_TOO_LARGE"
        ), response.text
        no_job(case)
        assert not case["calls"]
    finally:
        tariff(2097152)


@pytest.mark.parametrize("publication", ["published", "pending", "unknown_fee"])
def test_closed_project_runner_notifies_original_terminal_once(queued, publication):
    from packages.tasks import runner

    w = queued
    if publication == "unknown_fee":
        w["mode"] = "timeout"
    finish(w, publish=publication != "pending")
    mutate_authority(w, "closed")
    coordinator.tick([w["job_id"]])
    expected = {
        "published": "succeeded",
        "pending": "superseded",
        "unknown_fee": "reconciliation_required",
    }[publication]
    assert current(w)["state"] == expected
    after = UUID(int=UUID(w["bid"]).int - 1)
    calls = len(w["calls"])
    assert runner.cycle(after=after, limit=1)["provider_calls"] == 0
    assert runner.cycle(after=after, limit=1)["provider_calls"] == 0
    with connection() as c:
        notices = c.execute(
            "SELECT payload FROM design.audit_entries WHERE bid_id=%s AND event_type='task.notification'",
            (w["bid"],),
        ).fetchall()
        assert [n["payload"]["state"] for n in notices] == [expected]
    assert len(w["calls"]) == calls
