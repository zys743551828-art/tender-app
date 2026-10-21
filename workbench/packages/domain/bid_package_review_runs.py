"""Start an explicit scope review atomically; immutable ACK replay precedes fresh admission."""

from psycopg.types.json import Jsonb

from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_review_run_repository as repository
from packages.domain import bid_package_scope_review as admission
from packages.domain import package_scope_review as policy
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import Command, DomainError, audit, connection, enqueue_plan, sha, uid
from packages.identity import pagination


def start(actor, scope, frozen_id, prepared_id, key, body):
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(c, actor, scope, frozen_id, prepared_id, key, body)
    if old is not None:
        return old, True
    verified = admission.verify(admission.observe(scope, frozen_id, prepared_id, body))
    # Capacity is checked against the complete payload before accepting a queued job.
    policy.batches(verified._observed.model_input())
    with connection() as c:
        lock_bid(c, scope[0])
        command = Command(c, actor, repository.KIND, prepared_id, key, body)
        if command.replay is not None:
            repository.assert_scope(command.replay["body"], scope, frozen_id, prepared_id)
            return command.replay, True
        manifest = admission.recheck(c, verified)
        input_digest = digest(manifest)
        execution_key = admission.execution_key(verified, manifest)
        existing = c.execute(
            repository.SUMMARY_SELECT + " WHERE r.bid_id=%s AND r.execution_key=%s",
            (scope[0], execution_key),
        ).fetchone()
        if existing is not None:
            if existing["input_digest"] != input_digest:
                # Navigation records can be re-saved without changing the paid input.
                # Never project an earlier run beneath the newly prepared URL.
                raise DomainError(
                    "PACKAGE_REVIEW_ALREADY_EXISTS",
                    "相同实际输入已有核查运行；请查看原运行，或明确填写复检理由后创建新一轮",
                    409,
                    {"existing_run": repository.view(existing, summary=True)},
                )
            value = repository.load(c, scope, frozen_id, prepared_id, existing["id"])
            return command.finish(value, 202), False
        run_id = uid()
        operation = enqueue_plan(
            c,
            scope[0],
            command.id,
            "package-scope-review",
            {"id": str(run_id)},
            stages=[{"key": policy.STEP, "depends_on": [], "required": True}],
            handler_version=policy.HANDLER,
            topic="tender.task.review.v1",
            input_digest=input_digest,
        )
        c.execute(
            """INSERT INTO design.bid_package_review_runs
            (id,bid_id,execution_input_id,actor_id,command_id,operation_id,input_manifest,input_digest,execution_key)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                run_id,
                scope[0],
                prepared_id,
                actor,
                command.id,
                operation["id"],
                Jsonb(manifest),
                input_digest,
                execution_key,
            ),
        )
        value = repository.load(c, scope, frozen_id, prepared_id, run_id)
        audit(
            c,
            actor,
            scope[0],
            repository.EVENT,
            {
                "run_id": str(run_id),
                "operation_id": operation["id"],
                "input_digest": input_digest,
                "execution_input_id": prepared_id,
                "dependency_plan_id": body["dependency_plan_id"],
            },
            command.id,
        )
        return command.finish(value, 202), False


def read(scope, frozen_id, prepared_id, run_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.load(c, scope, frozen_id, prepared_id, run_id)


def read_input(scope, frozen_id, prepared_id, run_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        repository.load(c, scope, frozen_id, prepared_id, run_id)
        row = c.execute(
            "SELECT input_manifest,input_digest FROM design.bid_package_review_runs WHERE bid_id=%s AND execution_input_id=%s AND id=%s",
            (scope[0], prepared_id, run_id),
        ).fetchone()
        return {"manifest": row["input_manifest"], "digest": row["input_digest"]}


def directory(scope, frozen_id, prepared_id, limit=10, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainError("INVALID_REQUEST", "每页核查运行数量须为1至100", 422)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        prepared = prepared_inputs.load_packet(c, scope, frozen_id, prepared_id)
        binding = {
            "scope": dict(zip(repository.SCOPE_KEYS, scope, strict=True)),
            "frozen_input_id": frozen_id,
            "execution_input_id": prepared_id,
            "execution_input_digest": prepared.digest,
        }
        marker = sha({"directory": "package-review-runs/1", **binding})
        after = pagination.decode(cursor, marker)
        if after:
            try:
                if utc(after[0]) != after[0]:
                    raise ValueError("noncanonical time")
            except (ValueError, OverflowError) as error:
                raise DomainError("INVALID_CURSOR", "核查历史游标时间无效", 422) from error
        rows = c.execute(
            repository.SUMMARY_SELECT
            + """ WHERE r.bid_id=%s AND r.execution_input_id=%s
            AND (%s::timestamptz IS NULL OR (r.created_at,r.id)>(%s::timestamptz,%s::uuid))
            ORDER BY r.created_at,r.id LIMIT %s""",
            (
                scope[0],
                prepared_id,
                after[0] if after else None,
                after[0] if after else None,
                after[-1] if after else None,
                limit + 1,
            ),
        ).fetchall()
        items = [repository.view(row, summary=True) for row in rows[:limit]]
        for value in items:
            repository.assert_scope(value, scope, frozen_id, prepared_id)
        more = len(rows) > limit
        return {
            **binding,
            "items": items,
            "has_more": more,
            "next_cursor": pagination.encode(marker, [items[-1]["created_at"], items[-1]["id"]])
            if more
            else None,
        }
