"""Append human dispositions with exact ACK replay, one-row CAS and immutable history."""

from psycopg.types.json import Jsonb

from packages.domain import bid_package_review_decision_repository as repository
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import package_review_decisions as policy
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    connection,
    require_read_committed,
    sha,
    uid,
)
from packages.identity import pagination
from packages.lifecycle.service import assert_work_writable


def save(actor, scope, frozen_id, prepared_id, run_id, requirement_id, key, body):
    policy.request(body)
    if not isinstance(key, str) or not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(
            c, actor, scope, frozen_id, prepared_id, run_id, requirement_id, key, body
        )
    if old is not None:
        return old, True
    with connection() as c:
        require_read_committed(c)
        lock_bid(c, scope[0])
        command = Command(c, actor, policy.KIND, run_id, key, body)
        if command.replay is not None:
            return repository.ack(
                command.replay, actor, scope, frozen_id, prepared_id, run_id, requirement_id, body
            ), True
        assert_work_writable(c, scope[0])
        run = runs.load(c, scope, frozen_id, prepared_id, run_id)
        policy.row(run, requirement_id)
        previous = repository.head(c, run, requirement_id, for_update=True)
        actual_head = (
            {"id": previous["manifest"]["id"], "digest": previous["digest"]}
            if previous is not None
            else None
        )
        if body["expected_head"] != actual_head:
            raise DomainError(
                "PACKAGE_REVIEW_DECISION_HEAD_CHANGED",
                "其他成员已更新此项人工处置，请读取当前状态后再决定",
                409,
                {"current_head": actual_head},
            )
        sequence_no = previous["manifest"]["sequence_no"] + 1 if previous is not None else 1
        stamp = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        value = policy.make(
            run,
            requirement_id,
            body,
            decision_id=str(uid()),
            actor_id=str(actor),
            created_at=utc(str(stamp)),
            sequence_no=sequence_no,
        )
        manifest = value["manifest"]
        c.execute(
            """INSERT INTO design.bid_package_review_decisions
            (id,bid_id,run_id,requirement_id,actor_id,command_id,sequence_no,
             previous_id,previous_digest,manifest,digest,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                manifest["id"],
                scope[0],
                run_id,
                requirement_id,
                actor,
                command.id,
                sequence_no,
                actual_head["id"] if actual_head else None,
                actual_head["digest"] if actual_head else None,
                Jsonb(manifest),
                value["digest"],
                manifest["created_at"],
            ),
        )
        if actual_head is None:
            c.execute(
                """INSERT INTO design.bid_package_review_decision_heads
                (bid_id,run_id,requirement_id,decision_id,digest,sequence_no)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (scope[0], run_id, requirement_id, manifest["id"], value["digest"], sequence_no),
            )
        else:
            changed = c.execute(
                """UPDATE design.bid_package_review_decision_heads SET decision_id=%s,digest=%s,sequence_no=%s
                WHERE bid_id=%s AND run_id=%s AND requirement_id=%s AND decision_id=%s AND digest=%s""",
                (
                    manifest["id"],
                    value["digest"],
                    sequence_no,
                    scope[0],
                    run_id,
                    requirement_id,
                    actual_head["id"],
                    actual_head["digest"],
                ),
            ).rowcount
            policy.require(
                changed == 1,
                "PACKAGE_REVIEW_DECISION_HEAD_CHANGED",
                "当前人工处置已变化，未保存覆盖写入",
            )
        audit(c, actor, scope[0], policy.EVENT, repository.event(value), command.id)
        return command.finish(value, 201), False


def current(scope, frozen_id, prepared_id, run_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.current(c, runs.load(c, scope, frozen_id, prepared_id, run_id))


def history(scope, frozen_id, prepared_id, run_id, requirement_id, *, limit=20, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise DomainError("INVALID_REQUEST", "每页人工处置历史数量须为1至20", 422)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        run = runs.load(c, scope, frozen_id, prepared_id, run_id)
        original = policy.row(run, requirement_id)
        binding = {
            **policy.binding(run),
            "requirement_id": requirement_id,
            "row_digest": digest(original),
        }
        marker = sha({"directory": "package-review-human-decisions/1", **binding})
        after = pagination.decode(cursor, marker)
        if after:
            try:
                sequence = int(after[0])
                if not 1 <= sequence <= 9007199254740991 or str(sequence) != after[0]:
                    raise ValueError("sequence")
            except (ValueError, OverflowError) as error:
                raise DomainError("INVALID_CURSOR", "人工处置历史游标版本无效", 422) from error
        rows = c.execute(
            """SELECT * FROM design.bid_package_review_decisions
            WHERE bid_id=%s AND run_id=%s AND requirement_id=%s
            AND (%s::bigint IS NULL OR (sequence_no,id)<(%s::bigint,%s::uuid))
            ORDER BY sequence_no DESC,id DESC LIMIT %s""",
            (
                scope[0],
                run_id,
                requirement_id,
                after[0] if after else None,
                after[0] if after else None,
                after[-1] if after else None,
                limit + 1,
            ),
        ).fetchall()
        items = [repository.view(row, run, requirement_id) for row in rows[:limit]]
        more = len(rows) > limit
        return {
            **binding,
            "items": items,
            "has_more": more,
            "next_cursor": pagination.encode(
                marker, [str(items[-1]["manifest"]["sequence_no"]), items[-1]["manifest"]["id"]]
            )
            if more
            else None,
        }
