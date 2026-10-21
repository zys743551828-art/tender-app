"""Immutable run identity and historical reads; no fresh provider or source admission."""

from packages.contracts.package_review_runs_api import valid
from packages.domain import package_scope_review as policy
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import DomainError, clean, sha

KIND = "package-scope-review-start"
EVENT = "package.scope_review.started"
SCOPE_KEYS = ("bid_id", "package_id", "revision_id", "inventory_id")
SELECT = """SELECT r.*,o.kind AS operation_kind,o.state AS operation_state,
o.input_digest AS operation_input_digest,o.handler_version,
o.created_at AS operation_created_at,o.finished_at,
coalesce((SELECT s.output->>'error_code' FROM design.step_receipts s
 WHERE s.operation_id=o.id AND s.step_key='scope-judgment' AND s.input_digest=o.input_digest),
 (SELECT a.payload->>'error_code' FROM design.audit_entries a
 WHERE a.bid_id=r.bid_id AND a.payload->>'operation_id'=o.id::text
 AND a.event_type='operation.work_closed' ORDER BY a.created_at DESC,a.id DESC LIMIT 1)) AS error_code,
x.manifest AS result_manifest,x.digest AS result_digest
FROM design.bid_package_review_runs r JOIN design.operations o ON o.id=r.operation_id AND o.bid_id=r.bid_id
LEFT JOIN design.bid_package_review_results x ON x.run_id=r.id AND x.bid_id=r.bid_id AND x.operation_id=r.operation_id"""
SUMMARY_SELECT = SELECT.replace(
    "x.manifest AS result_manifest",
    """CASE WHEN x.run_id IS NULL THEN NULL ELSE jsonb_build_object(
        'requirement_count',x.manifest->'requirement_count',
        'matrix_coverage',x.manifest->'matrix_coverage',
        'overall_coverage',x.manifest->'overall_coverage') END AS result_summary""",
)


def assert_scope(view, scope, frozen_id, prepared_id):
    if (
        tuple(view["scope"][key] for key in SCOPE_KEYS) != scope
        or view["frozen_input_id"] != frozen_id
        or view["execution_input_id"] != prepared_id
    ):
        raise DomainError("PACKAGE_REVIEW_RUN_NOT_FOUND", "该准备输入下没有这条核查运行", 404)


def replay(c, actor, scope, frozen_id, prepared_id, key, body):
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, KIND, prepared_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同核查输入", 409)
    response = row["response"]
    if response is None:
        raise DomainError("COMMAND_INCOMPLETE", "原核查启动命令尚未完成", 409)
    if response["status"] != 202 or not valid("PackageReviewRunView", response["body"]):
        raise DomainError("PACKAGE_REVIEW_RUN_CORRUPT", "原核查启动回执无法核验", 500)
    assert_scope(response["body"], scope, frozen_id, prepared_id)
    return response


def view(row, *, summary=False):
    row = clean(row)
    manifest = row["input_manifest"]
    try:
        policy.validate_input(manifest)
        if (
            digest(manifest) != row["input_digest"]
            or row["input_digest"] != row["operation_input_digest"]
            or row["bid_id"] != manifest["scope"]["bid_id"]
            or row["execution_input_id"] != manifest["execution_input"]["id"]
        ):
            raise ValueError("run identity")
        result = None
        if summary:
            if row["result_summary"] is not None:
                result = {"digest": row["result_digest"], **row["result_summary"]}
        elif row["result_manifest"] is not None:
            result = {"manifest": row["result_manifest"], "digest": row["result_digest"]}
            rm = result["manifest"]
            policy.validate_contract("Result", rm)
            if (
                digest(rm) != result["digest"]
                or rm["run_id"] != row["id"]
                or rm["bid_id"] != row["bid_id"]
                or rm["scope"] != manifest["scope"]
                or rm["input_digest"] != row["input_digest"]
                or rm["execution_input_id"] != manifest["execution_input"]["id"]
                or rm["execution_input_digest"] != manifest["execution_input"]["digest"]
                or rm["execution_digest"]
                != manifest["execution_input"]["identity"]["execution_digest"]
                or rm["dependency_plan_id"] != manifest["dependency_plan"]["id"]
                or rm["dependency_plan_digest"] != manifest["dependency_plan"]["digest"]
                or rm["method_digest"] != manifest["executor_method"]["digest"]
            ):
                raise ValueError("result identity")
        if (row["operation_state"] == "succeeded") != (result is not None):
            raise ValueError("terminal result")
        value = {
            "kind": "package_review_run",
            "id": row["id"],
            "actor_id": row["actor_id"],
            "created_at": utc(row["created_at"]),
            "scope": manifest["scope"],
            "frozen_input_id": manifest["frozen_input"]["id"],
            "frozen_input_digest": manifest["frozen_input"]["digest"],
            "execution_input_id": manifest["execution_input"]["id"],
            "execution_input_digest": manifest["execution_input"]["digest"],
            "execution_digest": manifest["execution_input"]["identity"]["execution_digest"],
            "dependency_plan_id": manifest["dependency_plan"]["id"],
            "dependency_plan_digest": manifest["dependency_plan"]["digest"],
            "input_digest": row["input_digest"],
            "method_digest": manifest["executor_method"]["digest"],
            "operation": {
                "id": row["operation_id"],
                "kind": row["operation_kind"],
                "state": row["operation_state"],
                "input_digest": row["operation_input_digest"],
                "handler_version": row["handler_version"],
                "error_code": row["error_code"] if row["operation_state"] == "failed" else None,
                "created_at": utc(row["operation_created_at"]),
                "finished_at": utc(row["finished_at"]) if row["finished_at"] else None,
            },
            "result": result,
        }
        if not valid("PackageReviewRunSummary" if summary else "PackageReviewRunView", value):
            raise ValueError("run contract")
        return value
    except (KeyError, TypeError, ValueError, DomainError) as error:
        raise DomainError(
            "PACKAGE_REVIEW_RUN_CORRUPT", "核查身份、任务或原报告无法一致核验", 500
        ) from error


def load(c, scope, frozen_id, prepared_id, run_id):
    row = c.execute(
        SELECT + " WHERE r.bid_id=%s AND r.execution_input_id=%s AND r.id=%s",
        (scope[0], prepared_id, run_id),
    ).fetchone()
    if row is None:
        raise DomainError("PACKAGE_REVIEW_RUN_NOT_FOUND", "核查运行不存在", 404)
    value = view(row)
    assert_scope(value, scope, frozen_id, prepared_id)
    return value
