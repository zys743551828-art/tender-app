"""Freeze explicit human heads for an asynchronous historical report copy."""

from psycopg.types.json import Jsonb

from packages.domain import bid_package_report_repository as repository
from packages.domain import bid_package_review_decision_repository as decisions
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import package_review_reports as policy
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import Command, DomainError, audit, connection, enqueue_plan, sha, uid
from packages.identity import pagination


def read_context(scope, frozen_id, prepared_id, run_id):
    # Local binary/font probes are outside every database transaction.
    profile, unavailable = policy.method_profile()
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        run = runs.load(c, scope, frozen_id, prepared_id, run_id)
        public, _ = policy.context(run, decisions.current(c, run), profile, unavailable)
        return public


def start(actor, scope, frozen_id, prepared_id, run_id, key, body):
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的报告申请幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(c, actor, scope, frozen_id, prepared_id, run_id, key, body)
    if old is not None:
        return old, True
    profile, unavailable = policy.method_profile()
    with connection() as c:
        lock_bid(c, scope[0])
        command = Command(c, actor, policy.KIND, run_id, key, body)
        if command.replay is not None:
            repository.assert_scope(command.replay["body"], scope, frozen_id, prepared_id, run_id)
            return command.replay, True
        run = runs.load(c, scope, frozen_id, prepared_id, run_id)
        public, context = policy.context(run, decisions.current(c, run), profile, unavailable)
        if public["context_digest"] != body["context_digest"]:
            raise DomainError(
                "PACKAGE_REVIEW_REPORT_CONTEXT_CHANGED",
                "人工记录或报告方法已变化，请读取当前生成依据后重试",
                409,
            )
        snapshot = policy.freeze(context, body["format"])
        identity = digest(snapshot)
        # Failed/cancelled zero-model render attempts can be explicitly retried.
        # Active or successful identical copies are reused under the project lock.
        existing = c.execute(
            "SELECT r.id FROM design.bid_package_report_exports r JOIN design.operations o ON o.id=r.operation_id AND o.bid_id=r.bid_id WHERE r.bid_id=%s AND r.input_digest=%s AND o.state IN('queued','running','cancel_requested','succeeded') ORDER BY r.created_at,r.id LIMIT 1",
            (scope[0], identity),
        ).fetchone()
        if existing is not None:
            return command.finish(
                repository.load(c, scope, frozen_id, prepared_id, run_id, existing["id"]), 202
            ), False
        export_id = uid()
        operation = enqueue_plan(
            c,
            scope[0],
            command.id,
            "package-scope-report",
            {"id": str(export_id)},
            stages=[{"key": policy.STEP, "depends_on": [], "required": True}],
            handler_version=policy.HANDLER,
            topic="tender.task.export.v1",
            input_digest=identity,
        )
        c.execute(
            "INSERT INTO design.bid_package_report_exports(id,bid_id,run_id,actor_id,command_id,operation_id,input_manifest,input_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                export_id,
                scope[0],
                run_id,
                actor,
                command.id,
                operation["id"],
                Jsonb(snapshot),
                identity,
            ),
        )
        value = repository.load(c, scope, frozen_id, prepared_id, run_id, export_id)
        audit(
            c,
            actor,
            scope[0],
            policy.EVENT,
            {
                "export_id": str(export_id),
                "run_id": run_id,
                "operation_id": operation["id"],
                "report_input_digest": identity,
                "context_digest": snapshot["context_digest"],
                "format": body["format"],
            },
            command.id,
        )
        return command.finish(value, 202), False


def read(scope, frozen_id, prepared_id, run_id, export_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.load(c, scope, frozen_id, prepared_id, run_id, export_id)


def directory(scope, frozen_id, prepared_id, run_id, *, limit=10, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise DomainError("INVALID_REQUEST", "每页报告数量须为1至50", 422)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        run = runs.load(c, scope, frozen_id, prepared_id, run_id)
        binding = policy.binding(run)
        marker = sha({"directory": "package-review-reports/1", **binding})
        after = pagination.decode(cursor, marker)
        if after:
            try:
                if utc(after[0]) != after[0]:
                    raise ValueError("time")
            except (ValueError, OverflowError) as error:
                raise DomainError("INVALID_CURSOR", "报告历史游标时间无效", 422) from error
        rows = c.execute(
            repository.SELECT
            + " WHERE r.bid_id=%s AND r.run_id=%s AND (%s::timestamptz IS NULL OR (r.created_at,r.id)>(%s::timestamptz,%s::uuid)) ORDER BY r.created_at,r.id LIMIT %s",
            (
                scope[0],
                run_id,
                after[0] if after else None,
                after[0] if after else None,
                after[-1] if after else None,
                limit + 1,
            ),
        ).fetchall()
        items = [repository.view(row) for row in rows[:limit]]
        for value in items:
            repository.assert_scope(value, scope, frozen_id, prepared_id, run_id)
        more = len(rows) > limit
        return {
            **binding,
            "items": items,
            "has_more": more,
            "next_cursor": pagination.encode(marker, [items[-1]["created_at"], items[-1]["id"]])
            if more
            else None,
        }
