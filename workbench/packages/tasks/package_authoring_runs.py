"""Explicit manual exact chapter acceptance with original IO outside transactions."""

from uuid import UUID

from packages.authoring import package_admission as admission
from packages.authoring import package_input_repository as inputs
from packages.authoring import package_job_authority as authority
from packages.authoring.package_job_identity import selected
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    clean,
    connection,
    fetch,
    match,
    sha,
)
from packages.lifecycle.service import assert_work_writable, lock
from packages.tasks import templates

COMMAND = "task-package-authoring-run"


def replay(c, bid, definition, actor, key, body, condition):
    row = c.execute(
        "SELECT id,target_id,request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, COMMAND, definition, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": condition}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一命令键对应其他请求", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "原编写命令尚未完成", 409)
    from packages.tasks.package_authoring_result import accepted_receipt

    response = row["response"]
    accepted = response["body"]
    task = fetch(
        c,
        "SELECT * FROM design.task_runs WHERE bid_id=%s AND id=%s",
        (bid, UUID(accepted["id"])),
    )
    return accepted_receipt(c, task, row)


def start(actor, bid, definition, key, condition, body, *, final_auth):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        previous = replay(c, bid, definition, actor, key, body, condition)
        if previous is not None:
            return previous, True
        original = templates.current(c, bid, definition)
        config = original["config"]["definition"]
        if config["source_selection"]["mode"] != "exact_package_authoring":
            return None
        authority.require_schema(c)
        match(condition, "task-template", definition, original["revision"])
        if original["paused"]:
            raise DomainError("TASK_TEMPLATE_PAUSED", "模板已暂停", 409)
        if body != {"rerun": False}:
            raise DomainError(
                "AUTHORING_PACKAGE_RERUN_NOT_SUPPORTED",
                "固定整包章节任务复用原请求，不开放强制重发",
                409,
            )
        row = selected(c, bid, config["source_selection"]["input"], config["section_id"])
        inputs.declarations_match(c, row)
        original, row = clean(original), dict(row)
    observed = admission.observe(str(bid), row["manifest"]["selection"])
    if observed._context_text != row["context_text"]:
        raise DomainError("AUTHORING_PACKAGE_INPUT_CHANGED", "当前资格与已保存完整输入不一致", 409)
    verified = admission.verify(observed)
    with connection() as c:
        lock(c, bid)
        previous = replay(c, bid, definition, actor, key, body, condition)
        if previous is not None:
            return previous, True
        current = templates.current(c, bid, definition)
        match(condition, "task-template", definition, current["revision"])
        assert_work_writable(c, bid)
        if current["paused"] or clean(current) != original:
            raise DomainError(
                "AUTHORING_PACKAGE_TEMPLATE_CHANGED", "原件核验期间模板已变化或暂停", 409
            )
        admission.recheck(c, verified)
        row = selected(c, bid, config["source_selection"]["input"], config["section_id"])
        inputs.declarations_match(c, row)
        if str(final_auth()) != str(actor):
            raise DomainError("SESSION_CHANGED", "确认会话已变化，未创建编写任务", 401)
        command = Command(c, actor, COMMAND, definition, key, body, condition)
        if command.replay is not None:
            return command.replay, True
        old = c.execute(
            "SELECT t.id FROM design.task_runs t JOIN design.authoring_package_job_bindings b ON b.task_run_id=t.id "
            "WHERE b.bid_id=%s AND b.definition_version_id=%s AND b.input_id=%s AND b.input_digest=%s ORDER BY t.id LIMIT 1",
            (bid, current["version_id"], row["id"], row["digest"]),
        ).fetchone()
        if old:
            run_id, reused = old["id"], True
        else:
            from packages.authoring.package_jobs import queue

            run_id, reused = queue(c, bid, actor, current, row, command.id)
        if reused:
            audit(
                c,
                actor,
                bid,
                "task.run_reused",
                {
                    "run_id": run_id,
                    "definition_version_id": current["version_id"],
                    "trigger": "manual",
                    "trigger_event_id": None,
                    "scheduled_at": None,
                },
                command.id,
            )
        from packages.tasks.runs import view

        value = view(c, bid, run_id)
        return command.finish(value, 202, {"Task-Run-Reused": "true" if reused else "false"}), False
