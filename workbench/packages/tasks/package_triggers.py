"""Durable bounded wakeups of an explicitly saved package input.

Acceptance records an immutable intent under the project lock. Original-object
verification runs only after that connection closes. A short final transaction
rechecks the saved version and source authority and binds the native operation.
"""

from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

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
from packages.tasks import package_runs, templates

SCHEMA = "task-package-trigger-intent/1"
SELECT = """SELECT i.*,r.state AS resolution_state,r.error_code,r.task_run_id,r.reused
FROM design.task_package_trigger_intents i
LEFT JOIN design.task_package_trigger_resolutions r ON r.intent_id=i.id"""


def available(c):
    return bool(
        c.execute(
            "SELECT to_regclass('design.task_package_trigger_intents') IS NOT NULL "
            "AND to_regclass('design.task_package_trigger_resolutions') IS NOT NULL AS ready"
        ).fetchone()["ready"]
    )


def load(c, bid, identity):
    row = fetch(c, SELECT + " WHERE i.bid_id=%s AND i.id=%s", (bid, identity))
    m = row["manifest"]
    if sha(m) != row["input_digest"] or m.get("schema") != SCHEMA:
        raise DomainError("TASK_PACKAGE_TRIGGER_CORRUPT", "触发冻结记录无法核验", 500)
    return row


def view(row):
    return clean(
        {
            "id": row["id"],
            "bid_id": row["bid_id"],
            "definition_id": row["definition_id"],
            "definition_version_id": row["definition_version_id"],
            "trigger": row["trigger"],
            "trigger_event_id": row["trigger_event_id"],
            "scheduled_at": row["scheduled_at"],
            "created_at": row["created_at"],
            "selection": row["manifest"]["configuration"]["definition"]["source_selection"][
                "input"
            ],
            "input_digest": row["input_digest"],
            "state": row.get("resolution_state") or "pending",
            "error_code": row.get("error_code"),
            "run_id": row.get("task_run_id"),
            "run_ref": (
                f"/api/v1/bids/{row['bid_id']}/task-runs/{row['task_run_id']}"
                if row.get("task_run_id")
                else None
            ),
            "reused": bool(row.get("reused")),
            "automatic_input_selection": False,
        }
    )


def page(c, bid, after=None, limit=20):
    if not available(c):
        return {"items": [], "next_after": None}
    anchor = (
        fetch(
            c,
            "SELECT id,created_at FROM design.task_package_trigger_intents WHERE bid_id=%s AND id=%s",
            (bid, after),
        )
        if after
        else None
    )
    at = anchor["created_at"] if anchor else None
    rows = c.execute(
        sql.SQL(
            "{} WHERE i.bid_id=%s AND (%s::timestamptz IS NULL "
            "OR (i.created_at,i.id)>(%s::timestamptz,%s::uuid)) "
            "ORDER BY i.created_at,i.id LIMIT %s"
        ).format(sql.SQL(SELECT)),
        (bid, at, at, after, limit + 1),
    ).fetchall()
    return {
        "items": [view(row) for row in rows[:limit]],
        "next_after": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
    }


def assert_run_binding(c, row, binding):
    frozen = row["frozen_manifest"]
    if frozen.get("schema") != inputs.TRIGGER_SCHEMA:
        return
    intent = load(c, row["bid_id"], frozen["trigger_intent_id"])
    parent = fetch(c, "SELECT * FROM commands WHERE id=%s", (binding["parent_command_id"],))
    if (
        str(intent["definition_version_id"]) != str(row["definition_version_id"])
        or str(intent["actor_id"]) != frozen["actor_id"]
        or intent["manifest"]["configuration"]["definition"] != frozen["configuration"]
        or clean(intent["trigger_event_id"]) != frozen["trigger_event_id"]
        or clean(intent["scheduled_at"]) != frozen["scheduled_at"]
        or intent["trigger"] != frozen["trigger"]
        or parent["command_kind"] != "task-package-trigger-run"
        or str(parent["target_id"]) != str(intent["id"])
        or parent["request_digest"]
        != sha(
            {
                "body": {"intent_id": str(intent["id"]), "intent_digest": intent["input_digest"]},
                "if_match": None,
            }
        )
    ):
        raise ValueError("automatic package trigger binding")


def register(
    c, *, bid, definition, actor, command, trigger, key, event_id, scheduled_at, schedule_id
):
    if not available(c):
        raise DomainError("TASK_PACKAGE_TRIGGER_NOT_READY", "整包触发存储尚未安装", 503)
    lock(c, bid)
    assert_work_writable(c, bid)
    row = templates.current(c, bid, definition)
    config = row["config"]["definition"]
    if not inputs.is_trigger(config) or config["trigger"]["mode"] != trigger:
        raise DomainError("TASK_PACKAGE_TRIGGER_MISMATCH", "触发类型与已保存的明确模板不同", 409)
    if row["paused"]:
        raise DomainError("TASK_TEMPLATE_PAUSED", "模板已暂停", 409)
    inputs.selected(c, bid, inputs.selection(config))
    event_snapshot = None
    if event_id is not None:
        event = fetch(
            c,
            "SELECT payload FROM audit_entries WHERE bid_id=%s AND id=%s AND event_type='materials.committed'",
            (bid, event_id),
        )
        event_snapshot = event["payload"]["snapshot_id"]
    identity, accepted = uid(), templates.clock(c)
    manifest = clean(
        {
            "schema": SCHEMA,
            "id": identity,
            "bid_id": bid,
            "definition_id": definition,
            "definition_version_id": row["version_id"],
            "configuration_digest": row["digest"],
            "configuration": row["config"],
            "actor_id": actor,
            "request_command_id": command,
            "trigger": trigger,
            "trigger_key": key,
            "trigger_event_id": event_id,
            "event_snapshot_id": event_snapshot,
            "schedule_id": schedule_id,
            "scheduled_at": scheduled_at,
            "accepted_at": accepted,
        }
    )
    c.execute(
        """INSERT INTO design.task_package_trigger_intents
        (id,bid_id,definition_id,definition_version_id,actor_id,request_command_id,trigger_key,
        trigger,trigger_event_id,schedule_id,scheduled_at,manifest,input_digest,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identity,
            bid,
            definition,
            row["version_id"],
            actor,
            command,
            key,
            trigger,
            event_id,
            schedule_id,
            scheduled_at,
            Jsonb(manifest),
            sha(manifest),
            accepted,
        ),
    )
    return {
        "key": key,
        "trigger": trigger,
        "event_id": str(event_id) if event_id else None,
        "run_id": None,
        "reused": False,
        "state": "pending",
        "error_code": None,
        "intent_id": str(identity),
    }


def assert_current(c, row, *, readonly=False):
    if readonly:
        profile = fetch(
            c, "SELECT phase,archived_at FROM bid_profiles WHERE bid_id=%s", (row["bid_id"],)
        )
        if profile["archived_at"] or profile["phase"] in ("closed", "terminated"):
            raise DomainError("PROJECT_WORK_CLOSED", "项目已结束或归档", 409)
    else:
        assert_work_writable(c, row["bid_id"])
    definition = templates.current(c, row["bid_id"], row["definition_id"])
    if definition["paused"]:
        raise DomainError("TASK_TEMPLATE_PAUSED", "原触发后模板已暂停，未启动新工作", 409)
    m = row["manifest"]
    if (
        str(definition["version_id"]) != m["definition_version_id"]
        or definition["digest"] != m["configuration_digest"]
        or clean(definition["config"]) != m["configuration"]
    ):
        raise DomainError(
            "TASK_PACKAGE_TEMPLATE_CHANGED", "原触发后的模板版本已变化，未自动切换输入", 409
        )
    if row["trigger"] == "material_updated":
        profile = fetch(
            c, "SELECT current_material_id FROM bid_profiles WHERE bid_id=%s", (row["bid_id"],)
        )
        if str(profile["current_material_id"]) != m["event_snapshot_id"]:
            raise DomainError(
                "TASK_EVENT_SUPERSEDED", "原触发的资料事件已被更新，未转用新事件或新包", 409
            )
    else:
        schedule = fetch(
            c,
            "SELECT * FROM schedules WHERE bid_id=%s AND id=%s",
            (row["bid_id"], row["schedule_id"]),
        )
        if schedule["paused"] or schedule["definition_revision"] != definition["revision"]:
            raise DomainError("TASK_PACKAGE_SCHEDULE_CHANGED", "原定时配置已变化", 409)
    return definition


def _finish(
    c,
    row,
    command,
    *,
    state,
    error=None,
    run_id=None,
    reused=False,
    run_command=None,
    request=None,
    condition=None,
):
    if request is None:
        request = {"intent_id": str(row["id"]), "intent_digest": row["input_digest"]}
    c.execute(
        """INSERT INTO design.task_package_trigger_resolutions
        (intent_id,bid_id,command_id,state,error_code,task_run_id,reused,run_command_id,request,if_match)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            row["id"],
            row["bid_id"],
            command.id,
            state,
            error,
            run_id,
            reused,
            run_command,
            Jsonb(request),
            condition,
        ),
    )
    if run_id and row["schedule_id"]:
        operation = fetch(
            c,
            "SELECT operation_id FROM task_runs WHERE bid_id=%s AND id=%s",
            (row["bid_id"], run_id),
        )
        c.execute(
            "INSERT INTO schedule_receipts(schedule_id,scheduled_at,operation_id) VALUES(%s,%s,%s)",
            (row["schedule_id"], row["scheduled_at"], operation["operation_id"]),
        )
    value = view(load(c, row["bid_id"], row["id"]))
    audit(
        c,
        command_actor(c, command.id),
        row["bid_id"],
        "task.package_trigger_resolved",
        {
            "intent_id": row["id"],
            "definition_version_id": row["definition_version_id"],
            "state": state,
            "error_code": error,
            "run_id": run_id,
            "reused": reused,
            "intent_ref": f"/api/v1/bids/{row['bid_id']}/task-package-trigger-intents/{row['id']}",
        },
        command.id,
    )
    return command.finish(value)


def command_actor(c, command):
    return fetch(c, "SELECT actor_id FROM commands WHERE id=%s", (command,))["actor_id"]


def _resolve(bid, identity, verified=None, error=None):
    with connection() as c:
        lock(c, bid)
        row = load(c, bid, identity)
        if row["resolution_state"]:
            return view(row)
        request = {"intent_id": str(identity), "intent_digest": row["input_digest"]}
        command = Command(
            c,
            row["actor_id"],
            "task-package-trigger-resolve",
            identity,
            row["trigger_key"],
            request,
        )
        if command.replay:
            return command.replay["body"]
        saved = None
        if error is None:
            try:
                with c.transaction():
                    current = assert_current(c, row)
                    m = row["manifest"]
                    saved, _ = package_runs._publish(
                        c,
                        bid=bid,
                        definition=row["definition_id"],
                        actor=row["actor_id"],
                        key=row["trigger_key"],
                        condition=None,
                        body=request,
                        original={
                            "version_id": m["definition_version_id"],
                            "digest": m["configuration_digest"],
                            "config": m["configuration"],
                        },
                        selected=inputs.selection(current["config"]["definition"]),
                        verified=verified,
                        intent=row,
                    )
            except DomainError as failure:
                error = failure.code
            except psycopg.IntegrityError:
                error = "TASK_PACKAGE_STORAGE_REJECTED"
        if saved is None:
            return _finish(c, row, command, state="blocked", error=error)["body"]
        run_command = fetch(
            c,
            "SELECT id FROM commands WHERE actor_id=%s AND command_kind='task-package-trigger-run' AND target_id=%s AND idempotency_key=%s",
            (row["actor_id"], identity, row["trigger_key"]),
        )["id"]
        return _finish(
            c,
            row,
            command,
            state="accepted",
            run_id=UUID(saved["body"]["id"]),
            reused=saved["headers"]["Task-Run-Reused"] == "true",
            run_command=run_command,
        )["body"]


def process(bid, identity):
    try:
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            row = load(c, bid, identity)
            if row["resolution_state"]:
                return view(row)
            current = assert_current(c, row, readonly=True)
            selected = inputs.selection(current["config"]["definition"])
            inputs.selected(c, bid, selected)
        verified = inputs.verify(bid, selected)
    except DomainError as failure:
        return _resolve(bid, identity, error=failure.code)
    return _resolve(bid, identity, verified=verified)


def drain(bid, limit=10):
    if not 1 <= limit <= 50:
        raise ValueError("TASK_TRIGGER_BATCH_LIMIT")
    with connection() as c:
        if not available(c):
            return []
        rows = c.execute(
            """SELECT i.id FROM design.task_package_trigger_intents i
            WHERE i.bid_id=%s AND NOT EXISTS(SELECT FROM design.task_package_trigger_resolutions r WHERE r.intent_id=i.id)
            ORDER BY i.created_at,i.id LIMIT %s""",
            (bid, limit),
        ).fetchall()
    return [process(bid, row["id"]) for row in rows]


def cancel(c, *, bid, identity, actor, key, reason, condition):
    lock(c, bid)
    row = load(c, bid, identity)
    command = Command(
        c, actor, "task-package-trigger-cancel", identity, key, {"reason": reason}, condition
    )
    if command.replay:
        return command.replay, True
    match(condition, "task-package-trigger-intent", identity, row["input_digest"])
    if row["resolution_state"] == "accepted":
        raise DomainError(
            "TASK_TRIGGER_ALREADY_ACCEPTED",
            "已关联原生运行，请使用该运行的取消入口",
            409,
            {"run_ref": view(row)["run_ref"]},
        )
    if row["resolution_state"]:
        return command.finish(view(row)), False
    return _finish(
        c,
        row,
        command,
        state="cancelled",
        error="TASK_TRIGGER_CANCELLED",
        request={"reason": reason},
        condition=condition,
    ), False
