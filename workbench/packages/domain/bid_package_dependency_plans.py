"""Explicit dependency plan saving; never admission, original IO or task creation."""

from packages.domain import bid_package_dependency_plan_repository as repository
from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain import package_dependency_plan as plans
from packages.domain import package_fact_usage as facts
from packages.domain import package_input_dependencies as dependencies
from packages.domain.bid_package_service import lock_bid
from packages.domain.package_dependency_limits import require_dependency_body
from packages.domain.review_identity import utc
from packages.domain.runtime import Command, DomainError, audit, connection, sha, uid
from packages.lifecycle.service import assert_work_writable


def _replay(c, scope, frozen_id, input_id, response):
    if not response or response.get("status") != 201 or response.get("headers") != {}:
        raise DomainError("PACKAGE_DEPENDENCY_PLAN_CORRUPT", "依赖计划回执无法核验", 500)
    try:
        plan_id = response["body"]["manifest"]["id"]
    except (KeyError, TypeError) as error:
        raise DomainError("PACKAGE_DEPENDENCY_PLAN_CORRUPT", "依赖计划回执无法核验", 500) from error
    value = repository.load(c, scope, frozen_id, input_id, plan_id)
    if response["body"] != value:
        raise DomainError("PACKAGE_DEPENDENCY_PLAN_CORRUPT", "依赖计划回执不一致", 500)
    return response, True


def save(actor, scope, frozen_id, input_id, key, body):
    try:
        plans.validate("Save", body)
    except ValueError as error:
        raise DomainError(
            "PACKAGE_DEPENDENCY_PLAN_INVALID", "依赖计划字段不符合协议", 422
        ) from error
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = c.execute(
            "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
            (actor, repository.KIND, input_id, key),
        ).fetchone()
        if old is not None:
            if old["request_digest"] != sha({"body": body, "if_match": None}):
                raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同输入", 409)
            return _replay(c, scope, frozen_id, input_id, old["response"])
    # An already accepted immutable command keeps its original ACK even when
    # its body exceeds today's new-write budget. No new write has begun here.
    require_dependency_body(body)
    with connection() as c:
        lock_bid(c, scope[0])
        cmd = Command(c, actor, repository.KIND, input_id, key, body)
        if cmd.replay is not None:
            return _replay(c, scope, frozen_id, input_id, cmd.replay)
        assert_work_writable(c, scope[0])
        packet = prepared_inputs.load_packet(c, scope, frozen_id, input_id)
        if packet.digest != body["execution_input_digest"]:
            raise DomainError(
                "PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不一致", 409
            )
        original = frozen_inputs.load_input(c, scope, frozen_id)
        try:
            usage = facts.select(packet, {"purpose": body["purpose"], "fact_ids": body["fact_ids"]})
            assessment = dependencies.assess(
                original,
                packet,
                usage,
                {
                    "purpose": body["purpose"],
                    "usage_digest": usage.digest,
                    "dependencies": body["dependencies"],
                },
            )
            if assessment.digest != body["assessment_digest"]:
                raise DomainError(
                    "PACKAGE_INPUT_DEPENDENCIES_CHANGED",
                    "核对摘要已变化，请重新核对后明确保存",
                    409,
                )
            value = plans.build(
                original,
                packet,
                usage,
                assessment,
                record_id=str(uid()),
                actor_id=actor,
                command_id=str(cmd.id),
                saved_at=utc(
                    c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat()
                ),
                body=body,
            ).view()
        except ValueError as error:
            if str(error) in {
                "input_dependency_frozen_binding",
                "input_dependency_projection_corrupt",
                "input_dependency_coverage_changed",
                "input_dependency_duplicate_requirement",
            }:
                raise DomainError(
                    "PACKAGE_EXECUTION_INPUT_CORRUPT", "原准备输入的要求投影无法一致核验", 500
                ) from error
            raise DomainError(
                "PACKAGE_DEPENDENCY_PLAN_INVALID", "依赖计划身份、选择或依据不符合协议", 422
            ) from error
        repository.append(c, value)
        audit(c, actor, scope[0], repository.EVENT, repository.audit_payload(value), cmd.id)
        stored = cmd.finish(value, 201)
    return stored, False


def read(scope, frozen_id, input_id, plan_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.load(c, scope, frozen_id, input_id, plan_id)
