"""Immutable report-export identity, ACK replay and historical artifact reads."""

from packages.contracts.package_review_reports_api import valid
from packages.domain import package_review_reports as policy
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import DomainError, clean, sha

SELECT = """SELECT r.*,o.kind AS operation_kind,o.state AS operation_state,
o.input_digest AS operation_input_digest,o.handler_version,o.created_at AS operation_created_at,o.finished_at,
(SELECT s.output->>'error_code' FROM design.step_receipts s WHERE s.operation_id=o.id
 AND s.step_key='render-package-report' AND s.input_digest=o.input_digest) AS error_code,
a.document_version_id,a.blob_digest,a.gaps,v.original_name,v.artifact_kind AS document_kind,
b.digest AS actual_blob_digest,b.byte_size,b.media_type
FROM design.bid_package_report_exports r
JOIN design.operations o ON o.id=r.operation_id AND o.bid_id=r.bid_id
LEFT JOIN design.bid_package_report_artifacts a ON a.export_id=r.id AND a.bid_id=r.bid_id AND a.operation_id=r.operation_id
LEFT JOIN design.document_versions v ON v.bid_id=r.bid_id AND v.id=a.document_version_id
LEFT JOIN design.blobs b ON b.id=v.blob_id"""


def assert_scope(value, scope, frozen_id, prepared_id, run_id):
    if (
        tuple(
            value["scope"][key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
        )
        != scope
        or value["frozen_input_id"] != frozen_id
        or value["execution_input_id"] != prepared_id
        or value["run_id"] != run_id
    ):
        raise DomainError("PACKAGE_REVIEW_REPORT_NOT_FOUND", "该运行下没有这份报告副本", 404)


def replay(c, actor, scope, frozen_id, prepared_id, run_id, key, body):
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, policy.KIND, run_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同报告申请", 409)
    response = row["response"]
    if response is None:
        raise DomainError("COMMAND_INCOMPLETE", "原报告申请尚未完成", 409)
    if response["status"] != 202 or not valid("PackageReviewReportView", response["body"]):
        raise DomainError("PACKAGE_REVIEW_REPORT_CORRUPT", "原报告申请回执无法核验", 500)
    assert_scope(response["body"], scope, frozen_id, prepared_id, run_id)
    if (
        response["body"]["context_digest"] != body["context_digest"]
        or response["body"]["format"] != body["format"]
    ):
        raise DomainError("PACKAGE_REVIEW_REPORT_CORRUPT", "原报告回执与申请不一致", 500)
    return response


def view(row):
    row = clean(row)
    try:
        snapshot = row["input_manifest"]
        context = snapshot["context"]
        if (
            not valid("PackageReviewReportInput", snapshot)
            or digest(snapshot) != row["input_digest"]
            or digest(context) != snapshot["context_digest"]
            or row["input_digest"] != row["operation_input_digest"]
            or context["run_id"] != row["run_id"]
            or context["scope"]["bid_id"] != row["bid_id"]
        ):
            raise ValueError("report identity")
        artifact = None
        if row["document_version_id"] is not None:
            if (
                row["actual_blob_digest"] != row["blob_digest"]
                or row["document_kind"] != "review_report"
                or row["media_type"] != policy.MEDIA[snapshot["format"]]
            ):
                raise ValueError("artifact identity")
            artifact = {
                "document_version_id": row["document_version_id"],
                "blob_digest": row["blob_digest"],
                "byte_size": row["byte_size"],
                "media_type": row["media_type"],
                "filename": row["original_name"],
                "gaps": row["gaps"],
            }
        if (row["operation_state"] == "succeeded") != (artifact is not None):
            raise ValueError("terminal artifact")
        result = {
            **{
                key: context[key]
                for key in (
                    "scope",
                    "frozen_input_id",
                    "execution_input_id",
                    "run_id",
                    "input_digest",
                    "result_digest",
                )
            },
            "id": row["id"],
            "actor_id": row["actor_id"],
            "created_at": utc(row["created_at"]),
            "context_digest": snapshot["context_digest"],
            "report_input_digest": row["input_digest"],
            "format": snapshot["format"],
            "artifact_kind": "review_report",
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
            "result": artifact,
            "formal_scoring_eligible": False,
            "submission_eligible": False,
        }
        if not valid("PackageReviewReportView", result):
            raise ValueError("report contract")
        return result
    except (ValueError, KeyError, TypeError) as error:
        raise DomainError(
            "PACKAGE_REVIEW_REPORT_CORRUPT", "报告副本、任务或文件身份无法一致核验", 500
        ) from error


def load(c, scope, frozen_id, prepared_id, run_id, export_id):
    row = c.execute(
        SELECT + " WHERE r.bid_id=%s AND r.run_id=%s AND r.id=%s", (scope[0], run_id, export_id)
    ).fetchone()
    if row is None:
        raise DomainError("PACKAGE_REVIEW_REPORT_NOT_FOUND", "报告副本不存在", 404)
    value = view(row)
    assert_scope(value, scope, frozen_id, prepared_id, run_id)
    return value
