"""Prepared-input persistence and immutable history; no current observations or provider IO."""

from packages.domain import bid_package_review_input_repository as originals
from packages.domain.package_execution_input import consume_packet
from packages.domain.runtime import DomainError, sha

KIND = "package-review-execution-input-save"


def replay(c, actor, scope, frozen_id, key, body):
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, KIND, frozen_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同输入", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "操作尚未完成", 409)
    m = row["response"]["body"]["manifest"]
    if tuple(m[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")) != scope:
        raise DomainError("PACKAGE_EXECUTION_INPUT_NOT_FOUND", "执行输入不存在", 404)
    return row["response"]


def load_packet(c, scope, frozen_id, input_id):
    row = c.execute(
        "SELECT manifest,digest,snapshot_text,snapshot_digest FROM design.bid_package_execution_inputs WHERE bid_id=%s AND manifest->>'package_id'=%s AND manifest->>'revision_id'=%s AND manifest->>'inventory_id'=%s AND frozen_input_id=%s AND id=%s",
        (*scope, frozen_id, input_id),
    ).fetchone()
    if row is None:
        raise DomainError("PACKAGE_EXECUTION_INPUT_NOT_FOUND", "执行输入不存在", 404)
    packet = originals.load_input(c, scope, frozen_id)
    return consume_packet(row, scope, frozen_id, input_id, packet)


def load(c, scope, frozen_id, input_id):
    return load_packet(c, scope, frozen_id, input_id).view()
