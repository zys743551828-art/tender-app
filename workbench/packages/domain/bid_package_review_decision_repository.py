"""Exact human-decision reads and ACK replay, independent of mutable project readiness."""

from packages.contracts.package_review_decisions_api import valid
from packages.domain import package_review_decisions as policy
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import DomainError, clean, sha

HEAD_SELECT = """SELECT d.*,h.requirement_id AS head_requirement_id,
h.digest AS head_digest,h.sequence_no AS head_sequence_no
FROM design.bid_package_review_decision_heads h
LEFT JOIN design.bid_package_review_decisions d
 ON d.bid_id=h.bid_id AND d.run_id=h.run_id AND d.requirement_id=h.requirement_id
 AND d.id=h.decision_id AND d.digest=h.digest AND d.sequence_no=h.sequence_no"""


def ack(value, actor, scope, frozen_id, prepared_id, run_id, requirement_id, body):
    if (
        not isinstance(value, dict)
        or set(value) != {"body", "status", "headers"}
        or value["status"] != 201
        or value["headers"] != {}
        or not valid("PackageReviewHumanDecisionView", value["body"])
    ):
        raise DomainError("PACKAGE_REVIEW_DECISION_CORRUPT", "原人工处置回执无法核验", 500)
    record = value["body"]
    manifest = record["manifest"]
    policy.assert_scope(record, scope, frozen_id, prepared_id, run_id, requirement_id)
    if (
        digest(manifest) != record["digest"]
        or manifest["actor_id"] != str(actor)
        or manifest["previous_head"] != body["expected_head"]
        or any(
            manifest[key] != body[key]
            for key in ("result_digest", "row_digest", "state", "reason", "selected_quotes")
        )
        or (manifest["sequence_no"] == 1) != (manifest["previous_head"] is None)
    ):
        raise DomainError("PACKAGE_REVIEW_DECISION_CORRUPT", "原人工处置回执与请求不一致", 500)
    return value


def replay(c, actor, scope, frozen_id, prepared_id, run_id, requirement_id, key, body):
    row = c.execute(
        """SELECT request_digest,response FROM design.commands
        WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s""",
        (actor, policy.KIND, run_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同人工处置", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "原人工处置命令尚未完成", 409)
    return ack(row["response"], actor, scope, frozen_id, prepared_id, run_id, requirement_id, body)


def view(row, run, requirement_id=None):
    try:
        row = clean(row)
        value = {"manifest": row["manifest"], "digest": row["digest"]}
        manifest = value["manifest"]
        previous = (
            {"id": row["previous_id"], "digest": row["previous_digest"]}
            if row["previous_id"] is not None
            else None
        )
        if (
            manifest["id"] != row["id"]
            or manifest["actor_id"] != row["actor_id"]
            or manifest["scope"]["bid_id"] != row["bid_id"]
            or manifest["run_id"] != row["run_id"]
            or manifest["requirement_id"] != row["requirement_id"]
            or manifest["sequence_no"] != row["sequence_no"]
            or manifest["created_at"] != utc(row["created_at"])
            or manifest["previous_head"] != previous
            or (row["previous_id"] is None) != (row["previous_digest"] is None)
        ):
            raise ValueError("stored identity")
        return policy.check(value, run, requirement_id)
    except (KeyError, ValueError, TypeError) as error:
        raise DomainError(
            "PACKAGE_REVIEW_DECISION_CORRUPT", "人工处置身份或存储摘要无法核验", 500
        ) from error


def head_view(row, run, requirement_id=None):
    value = view(row, run, requirement_id)
    manifest = value["manifest"]
    if (
        str(row["head_requirement_id"]) != manifest["requirement_id"]
        or row["head_digest"] != value["digest"]
        or row["head_sequence_no"] != manifest["sequence_no"]
    ):
        raise DomainError("PACKAGE_REVIEW_DECISION_CORRUPT", "当前人工处置头与历史记录不一致", 500)
    return value


def head(c, run, requirement_id, *, for_update=False):
    row = c.execute(
        HEAD_SELECT
        + " WHERE h.bid_id=%s AND h.run_id=%s AND h.requirement_id=%s"
        + (" FOR UPDATE OF h" if for_update else ""),
        (run["scope"]["bid_id"], run["id"], requirement_id),
    ).fetchone()
    return head_view(row, run, requirement_id) if row is not None else None


def current(c, run):
    binding = policy.binding(run)
    rows = c.execute(
        HEAD_SELECT + " WHERE h.bid_id=%s AND h.run_id=%s ORDER BY h.requirement_id LIMIT 401",
        (run["scope"]["bid_id"], run["id"]),
    ).fetchall()
    heads = {}
    for row in rows:
        value = head_view(row, run)
        requirement_id = value["manifest"]["requirement_id"]
        if requirement_id in heads:
            raise DomainError("PACKAGE_REVIEW_DECISION_CORRUPT", "当前人工处置条款重复", 500)
        heads[requirement_id] = {
            **{
                key: value["manifest"][key]
                for key in ("id", "sequence_no", "actor_id", "created_at", "state", "reason")
            },
            "digest": value["digest"],
        }
    originals = run["result"]["manifest"]["matrix"]
    value = {
        **binding,
        "items": [
            {
                "requirement_id": row["requirement_id"],
                "row_digest": digest(row),
                "current": heads.get(row["requirement_id"]),
            }
            for row in sorted(originals, key=lambda row: row["requirement_id"])
        ],
    }
    if not valid("PackageReviewHumanDecisionCurrent", value):
        raise DomainError("PACKAGE_REVIEW_DECISION_CORRUPT", "当前人工处置列表无法核验", 500)
    return value


def event(value):
    manifest = value["manifest"]
    return {
        "decision_id": manifest["id"],
        "decision_digest": value["digest"],
        "run_id": manifest["run_id"],
        "requirement_id": manifest["requirement_id"],
        "result_digest": manifest["result_digest"],
        "row_digest": manifest["row_digest"],
        "state": manifest["state"],
        "previous_decision_id": manifest["previous_head"]["id"]
        if manifest["previous_head"] is not None
        else None,
    }
