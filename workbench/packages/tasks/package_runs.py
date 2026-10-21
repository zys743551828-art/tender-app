"""Manual package task coordination with lock-free original IO and atomic native work."""

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from packages.domain import bid_package_review_runs as native_runs
from packages.domain import bid_package_scope_review as admission
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    clean,
    connection,
    fetch,
    match,
    sha,
    uid,
)
from packages.lifecycle.service import assert_work_writable, lock
from packages.tasks import package_inputs as inputs
from packages.tasks import package_repository as repository
from packages.tasks import templates


def available(c):
    return (
        c.execute("SELECT to_regclass('design.task_package_review_bindings') AS name").fetchone()[
            "name"
        ]
        is not None
    )


def _assert_request(body):
    if not isinstance(body, dict) or set(body) != {"rerun"} or type(body["rerun"]) is not bool:
        raise DomainError("TASK_PACKAGE_REQUEST_INVALID", "整包任务请求字段无效", 422)
    if body["rerun"]:
        raise DomainError(
            "TASK_PACKAGE_REPREPARE_REQUIRED",
            "复检须先明确保存含复检理由的新执行输入，再将其保存为任务模板版本；不能自动更换原输入",
            409,
        )


def _assert_unresolved(c, bid, context):
    unresolved = c.execute(
        """SELECT mc.id FROM design.model_calls mc
        JOIN design.bid_package_review_runs r ON r.operation_id=mc.operation_id
        WHERE r.bid_id=%s AND r.input_manifest->>'model_input_digest'=%s
        AND mc.state IN('reserved','unknown') LIMIT 1""",
        (bid, context["model_input_digest"]),
    ).fetchone()
    if unresolved:
        raise DomainError(
            "MODEL_CALL_REQUIRES_RECONCILIATION",
            "同一真实整包模型输入的原调用费用尚未核清，未授权新尝试",
            409,
            {"call_id": str(unresolved["id"]), "new_attempt_authorized": False},
        )


def _publish(
    c, *, bid, definition, actor, key, condition, body, original, selected, verified, intent=None
):
    lock(c, bid)
    previous = (
        repository.replay(c, bid, definition, actor, key, body, condition)
        if intent is None
        else None
    )
    if previous is not None:
        return previous, True
    row = templates.current(c, bid, definition)
    if intent is None:
        match(condition, "task-template", definition, row["revision"])
    assert_work_writable(c, bid)
    if row["paused"]:
        raise DomainError("TASK_TEMPLATE_PAUSED", "模板已暂停；在途任务没有取消", 409)
    if (
        clean(row["version_id"]) != original["version_id"]
        or row["digest"] != original["digest"]
        or clean(row["config"]) != original["config"]
    ):
        raise DomainError("TASK_PACKAGE_TEMPLATE_CHANGED", "原件核验期间模板版本已变化", 409)
    manifest = admission.recheck(c, verified)
    context = inputs.context(bid, selected, manifest)
    _assert_unresolved(c, bid, context)
    schema = inputs.SCHEMA if intent is None else inputs.TRIGGER_SCHEMA
    trigger = {
        "trigger": "manual" if intent is None else intent["trigger"],
        "trigger_event_id": None if intent is None else intent["trigger_event_id"],
        "scheduled_at": None if intent is None else intent["scheduled_at"],
    }
    digest = inputs.input_digest(row["version_id"], row["digest"], context, schema=schema)
    command = Command(
        c,
        actor,
        repository.COMMAND_KIND if intent is None else "task-package-trigger-run",
        definition if intent is None else intent["id"],
        key,
        body,
        condition,
    )
    if command.replay is not None:
        return command.replay, True
    old = c.execute(
        """SELECT * FROM task_runs WHERE bid_id=%s AND definition_version_id=%s
        AND frozen_manifest->>'schema'=%s AND frozen_manifest->>'input_digest'=%s
        ORDER BY id LIMIT 1""",
        (bid, row["version_id"], schema, digest),
    ).fetchone()
    if old is not None:
        value = repository.view(c, old)
        audit(
            c,
            actor,
            bid,
            "task.run_reused",
            {
                "run_id": old["id"],
                "definition_version_id": row["version_id"],
                **trigger,
            },
            command.id,
        )
        return command.finish(value, 202, {"Task-Run-Reused": "true"}), False
    child_key = "task-package:" + sha({"task_command_id": command.id})
    saved, _ = native_runs.start_verified(
        c,
        str(actor),
        inputs.scope(bid, selected),
        selected["frozen_input_id"],
        selected["execution_input_id"],
        child_key,
        inputs.request(selected),
        verified,
    )
    run = saved["body"]
    child = fetch(
        c,
        "SELECT id FROM commands WHERE actor_id=%s AND command_kind='package-scope-review-start' AND target_id=%s AND idempotency_key=%s",
        (actor, selected["execution_input_id"], child_key),
    )["id"]
    identity = uid()
    frozen = clean(
        {
            "schema": schema,
            "definition_id": definition,
            "definition_version_id": row["version_id"],
            "configuration_digest": row["digest"],
            "configuration": row["config"]["definition"],
            "task_kind": "denial_check",
            "purpose": row["purpose"],
            "actor_id": actor,
            "request_id": command.id,
            "context": context,
            "input_digest": digest,
            "fee_scope": inputs.fee_scope(context),
            **trigger,
            **({"trigger_intent_id": intent["id"]} if intent is not None else {}),
            "accepted_at": templates.clock(c),
            "formal_decisions_allowed": False,
            "package_review": {
                "run_id": run["id"],
                "operation_id": run["operation"]["id"],
                "start_command_id": child,
                "input_digest": run["input_digest"],
                "method_digest": run["method_digest"],
                "run_ref": inputs.run_ref(run),
            },
        }
    )
    c.execute(
        "INSERT INTO task_runs(id,bid_id,definition_version_id,operation_id,frozen_manifest) VALUES(%s,%s,%s,%s,%s)",
        (identity, bid, row["version_id"], UUID(run["operation"]["id"]), Jsonb(frozen)),
    )
    c.execute(
        """INSERT INTO design.task_package_review_bindings
        (task_run_id,bid_id,review_run_id,start_command_id,parent_command_id,manifest_digest)
        VALUES(%s,%s,%s,%s,%s,%s)""",
        (identity, bid, run["id"], child, command.id, sha(frozen)),
    )
    audit(
        c,
        actor,
        bid,
        "task.run_created",
        {
            "run_id": identity,
            "definition_version_id": row["version_id"],
            "operation_id": run["operation"]["id"],
            "input_digest": digest,
        },
        command.id,
    )
    value = repository.view(
        c, fetch(c, "SELECT * FROM task_runs WHERE bid_id=%s AND id=%s", (bid, identity))
    )
    return command.finish(value, 202, {"Task-Run-Reused": "false"}), False


def start(actor, bid, definition, key, condition, body, *, final_auth=None):
    """Return None for the existing single-body path; package ACKs replay unchanged."""
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        previous = repository.replay(c, bid, definition, actor, key, body, condition)
        if previous is not None:
            return previous, True
        row = templates.current(c, bid, definition)
        if not inputs.is_exact(row["config"]["definition"]):
            return None
        if inputs.is_trigger(row["config"]["definition"]):
            raise DomainError(
                "TASK_PACKAGE_TRIGGER_EXPLICIT_WAKEUP_REQUIRED",
                "自动模板只执行已登记的明确触发；单次手动执行请显式保存手动模板版本，输入不会自动变化",
                409,
            )
        if not available(c):
            raise DomainError("TASK_PACKAGE_EXECUTOR_NOT_READY", "精确整包任务存储尚未安装", 503)
        _assert_request(body)
        match(condition, "task-template", definition, row["revision"])
        if row["paused"]:
            raise DomainError("TASK_TEMPLATE_PAUSED", "模板已暂停；在途任务没有取消", 409)
        selected = inputs.selection(row["config"]["definition"])
        inputs.selected(c, bid, selected)
        original = clean(row)
    verified = inputs.verify(bid, selected)
    if final_auth is not None and final_auth() != actor:
        raise DomainError("SESSION_CHANGED", "执行期间登录身份已变化，请保留原请求", 401)
    try:
        with connection() as c:
            return _publish(
                c,
                bid=bid,
                definition=definition,
                actor=actor,
                key=key,
                condition=condition,
                body=body,
                original=original,
                selected=selected,
                verified=verified,
            )
    except psycopg.IntegrityError as error:
        raise DomainError(
            "TASK_PACKAGE_STORAGE_REJECTED", "整包任务的不可变绑定或原回执未通过存储核验", 409
        ) from error
