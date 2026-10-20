"""Atomic scope declarations with CAS and recoverable ACK; no review qualification."""

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain import bid_package_fact_scope_repository as repository
from packages.domain import package_fact_scope as policy
from packages.domain.bid_package_fact_provenance import read_proof
from packages.domain.bid_package_frozen_originals import capture
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import utc
from packages.domain.runtime import Command, DomainError, connection, sha, uid
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable


def _checked_replay(stored, scope, frozen_id, input_id):
    value = policy.verify(stored["body"])
    b = value["manifest"]["binding"]
    if (
        tuple(b[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")) != scope
        or b["frozen_input_id"] != frozen_id
        or b["execution_input_id"] != input_id
    ):
        raise DomainError("PACKAGE_FACT_SCOPE_NOT_FOUND", "事实范围绑定不存在", 404)
    return stored


def save(actor, scope, frozen_id, input_id, key, body):
    # This is an internal use case. HTTP registration requires its own contract/tests.
    policy.validate_change(body)
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = c.execute(
            """SELECT request_digest,response FROM design.commands
            WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s""",
            (actor, repository.KIND, input_id, key),
        ).fetchone()
        if old:
            if old["request_digest"] != sha({"body": body, "if_match": None}):
                raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同输入", 409)
            if old["response"] is None:
                raise DomainError("COMMAND_INCOMPLETE", "操作尚未完成", 409)
            return _checked_replay(old["response"], scope, frozen_id, input_id), True
    with connection() as c:
        lock_bid(c, scope[0])
        command = Command(c, actor, repository.KIND, input_id, key, body)
        if command.replay:
            return _checked_replay(command.replay, scope, frozen_id, input_id), True
        packet = inputs.load_packet(c, scope, frozen_id, input_id)
        if packet.digest != body["execution_input_digest"]:
            raise DomainError("PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不符", 409)
        previous = repository.head(c, scope[0], input_id, body["fact_id"])
        if (previous["digest"] if previous else None) != body["previous_digest"]:
            raise DomainError("PACKAGE_FACT_SCOPE_CHANGED", "事实范围绑定已变化，请重读后操作", 409)
        audit = {
            "record_id": str(uid()),
            "actor_id": actor,
            "command_id": str(command.id),
            "recorded_at": utc(
                c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat()
            ),
            "reason": body["reason"],
        }
        if body["action"] == "withdraw":
            if previous is None:
                raise DomainError("PACKAGE_FACT_SCOPE_NOT_FOUND", "事实范围绑定不存在", 404)
            value = policy.withdraw(previous, **audit)
        else:
            assert_work_writable(c, scope[0])
            lock_graph(c)
            binding = packet.view()["manifest"]["identity"]["binding"]
            current = capture(c, scope, frozen_id, binding["frozen_digest"])
            context = current["context"]["manifest"]
            selected = [
                item for item in context["facts"]["items"] if item["fact"]["id"] == body["fact_id"]
            ]
            if len(selected) != 1:
                raise DomainError("PACKAGE_FACT_NOT_FOUND", "事实不存在于明确准备输入", 404)
            proof = read_proof(c, scope[0], selected[0], context["as_of"])
            value = policy.declare(
                packet, current, body["fact_id"], proof, body["subject"], previous=previous, **audit
            )
        repository.append(c, value)
        stored = command.finish(value, 201)
    return stored, False
