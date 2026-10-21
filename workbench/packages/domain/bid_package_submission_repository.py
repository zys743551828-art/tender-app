"""One immutable package binding per native submission, with exact command replay."""

from copy import deepcopy

from packages.contracts.package_submissions_api import valid
from packages.domain import package_submission_gate
from packages.domain.bid_package_submission_observations import failure
from packages.domain.review_identity import canonical, utc
from packages.domain.runtime import DomainError, clean, sha

KIND = "package-submission-register"
MAX_BINDING_BYTES = 64 * 1024 * 1024


def require_schema(c):
    row = c.execute(
        "SELECT to_regclass('design.bid_package_submission_bindings') AS name"
    ).fetchone()
    if row["name"] is None:
        failure("UNAVAILABLE", "整包实际提交登记存储尚未安装", 503)
    if not c.execute(
        "SELECT has_table_privilege(current_user,'design.bid_package_submission_bindings','SELECT') AS ready"
    ).fetchone()["ready"]:
        failure("UNAVAILABLE", "当前运行角色尚未配置整包提交只读权限", 503)


def request_body(scope, body, supersedes):
    return {"scope": list(scope), "supersedes_id": supersedes, **deepcopy(body)}


def command_digest(scope, body, condition, supersedes):
    return sha({"body": request_body(scope, body, supersedes), "if_match": condition})


def _check_binding(row):
    try:
        row = clean(row)
        value = {"manifest": row["manifest"], "digest": row["digest"]}
        manifest = value["manifest"]
        selection = manifest["selection"]
        target = selection["target"]
        tm = target["manifest"]
        scope = (row["bid_id"], row["package_id"], row["revision_id"])
        inventory = selection["inventory"]
        authority = selection["authority"]
        run = manifest["review_run"]
        gate = manifest["gate"]["manifest"]
        if (
            len(canonical(value)) > MAX_BINDING_BYTES
            or not valid("PackageSubmissionBindingView", value)
            or sha(manifest) != value["digest"]
            or manifest["submission_id"] != row["submission_id"]
            or manifest["bid_id"] != row["bid_id"]
            or manifest["command_id"] != row["command_id"]
            or manifest["subject"]
            != {
                "kind": "bid_package",
                "bid_id": scope[0],
                "package_id": scope[1],
                "revision_id": scope[2],
                "package_digest": target["digest"],
            }
            or (tm["scope"]["bid_id"], tm["package_id"], tm["revision_id"]) != scope
            or manifest["package_identity"] != target["identity"]
            or manifest["recorded_identity"]
            != manifest["context"]["current"]["current"]["identity"]
            or manifest["selection_request"] != manifest["request"]["selection"]
            or manifest["input_digest"] != manifest["request"]["input_digest"]
            or (authority["manifest"]["revision_id"] if authority else None)
            != row["authority_revision_id"]
            or (inventory["manifest"]["id"] if inventory else None) != row["inventory_id"]
            or (run["id"] if run else None) != row["review_run_id"]
            or manifest["request_digest"]
            != command_digest(
                scope, manifest["request"], manifest["if_match"], manifest["supersedes_id"]
            )
            or manifest["input_digest"]
            != sha(
                {
                    key: manifest[key]
                    for key in (
                        "selection",
                        "selection_request",
                        "context",
                        "review_run",
                        "inventory_proof",
                    )
                }
            )
            or gate["subject"]
            != {**manifest["subject"], "identity_digest": target["identity"]["digest"]}
            or gate["policy_digest"] != manifest["context"]["method_digest"]
            or gate["checked_at"] != manifest["assessed_at"]
            or utc(manifest["submitted_at"]) != utc(manifest["request"]["submitted_at"])
            or manifest["evidence"] not in manifest["originals"]
            or "submission_attachment" not in manifest["evidence"]["roles"]
            or any(
                manifest["evidence"][key] != manifest["request"]["evidence"][key]
                for key in ("document_version_id", "digest", "byte_size")
            )
        ):
            raise ValueError("binding")
        package_submission_gate.validate_view(manifest["gate"])
        return value
    except (KeyError, TypeError, ValueError, DomainError, RecursionError) as error:
        raise DomainError("PACKAGE_SUBMISSION_CORRUPT", "整包提交原始绑定无法核验", 500) from error


def binding(c, bid, submission_id):
    require_schema(c)
    row = c.execute(
        "SELECT * FROM design.bid_package_submission_bindings WHERE bid_id=%s AND submission_id=%s",
        (bid, submission_id),
    ).fetchone()
    if row is None:
        failure("NOT_FOUND", "所选实际提交记录没有整包绑定", 404)
    return _check_binding(row)


def value(row, frozen):
    row = clean(row)
    manifest = frozen["manifest"]
    if (
        row["id"] != manifest["submission_id"]
        or row["bid_id"] != manifest["bid_id"]
        or row["subject_kind"] != "bid_package"
        or row["body_version_id"] is not None
        or row["review_id"] is not None
        or row["created_by"] != manifest["actor_id"]
        or row["kind"] != manifest["request"]["kind"]
        or row["supersedes_id"] != manifest["supersedes_id"]
        or utc(row["submitted_at"]) != manifest["submitted_at"]
        or utc(row["created_at"]) != manifest["recorded_at"]
        or row["gate_snapshot"] != manifest["gate"]
        or row["evidence"] != native_evidence(frozen)
    ):
        failure("CORRUPT", "原生实交记录与完整投标包绑定不一致", 500)
    checked = row["kind"] == "standard" and manifest["gate"]["manifest"]["allowed"] is True
    result = {
        "id": row["id"],
        "bid_id": row["bid_id"],
        "subject_kind": "bid_package",
        "body_version_id": None,
        "review_id": None,
        "kind": row["kind"],
        "submitted_at": manifest["submitted_at"],
        "recorded_at": manifest["recorded_at"],
        "recorded_by": row["created_by"],
        "gate_checked": checked,
        "evidence_ref": manifest["evidence"]["document_version_id"],
        "current": row["head_id"] == row["id"],
        "supersedes_id": row["supersedes_id"],
        "identity": manifest["package_identity"],
        "original_name": None,
        "artifact_kind": None,
        "checks_label": "核心提交检查已通过"
        if checked
        else "未经过系统完整检查；已记录完整投标包实际提交事实",
        "open_risk_snapshot": manifest["gate"]["manifest"]["gates"]["known_blocking_risks"],
        "platform_submission_verified": False,
        "explanation": manifest["request"]["explanation"],
        "correction_reason": manifest["request"]["correction_reason"],
        "package_binding": frozen,
    }
    if not valid("PackageSubmissionView", result):
        failure("CORRUPT", "整包实际提交视图无法核验", 500)
    return result


def native_evidence(frozen):
    m = frozen["manifest"]
    return {
        "evidence_ref": m["evidence"]["document_version_id"],
        "evidence_digest": m["evidence"]["digest"],
        "evidence_type": "user_declared_package_submission_attachment",
        "platform_submission_verified": False,
        "pre_submission_system_check_verified": False,
        "identity": m["package_identity"],
        "recorded_identity": m["recorded_identity"],
        "package_binding_digest": frozen["digest"],
        "actual_package": m["subject"],
        "registration_assessed_at": m["assessed_at"],
        "checks_label": "未经过系统完整检查；已记录完整投标包实际提交事实",
        "explanation": m["request"]["explanation"],
        "correction_reason": m["request"]["correction_reason"],
        "open_risk_snapshot": m["gate"]["manifest"]["gates"]["known_blocking_risks"],
    }


def load(c, bid, submission_id):
    frozen = binding(c, bid, submission_id)
    row = c.execute(
        "SELECT s.*,h.submission_id AS head_id FROM design.submission_records s LEFT JOIN design.submission_heads h ON h.bid_id=s.bid_id WHERE s.bid_id=%s AND s.id=%s",
        (bid, submission_id),
    ).fetchone()
    if row is None:
        failure("CORRUPT", "整包绑定缺少原生实际提交记录", 500)
    return value(row, frozen)


def replay(c, actor, scope, key, body, condition, supersedes):
    row = c.execute(
        "SELECT id::text,request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, KIND, scope[0], key),
    ).fetchone()
    if row is None:
        return None
    expected = command_digest(scope, body, condition, supersedes)
    if row["request_digest"] != expected:
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同的实际提交请求", 409)
    saved = row["response"]
    if saved is None:
        raise DomainError("COMMAND_INCOMPLETE", "原实际提交登记尚未完成", 409)
    try:
        ack = saved["body"]
        command = ack["command"]
        submission = ack["submission"]
        if (
            set(saved) != {"body", "status", "headers"}
            or saved["status"] != 201
            or not valid("PackageSubmissionAppliedView", ack)
            or set(saved["headers"]) != {"X-Bid-ETag"}
            or not isinstance(saved["headers"]["X-Bid-ETag"], str)
            or command
            != {
                "command_id": row["id"],
                "actor_id": actor,
                "idempotency_key": key,
                "request_digest": expected,
                "request": body,
                "if_match": condition,
            }
            or submission["bid_id"] != scope[0]
            or submission["supersedes_id"] != supersedes
            or not submission["current"]
        ):
            raise ValueError("receipt")
        frozen = binding(c, scope[0], submission["id"])
        if frozen != submission["package_binding"]:
            raise ValueError("binding")
        actual = load(c, scope[0], submission["id"])
        actual["current"] = True
        if actual != submission:
            raise ValueError("native record")
    except (KeyError, TypeError, ValueError, DomainError) as error:
        raise DomainError(
            "PACKAGE_SUBMISSION_ACK_CORRUPT", "原实际提交回执与请求无法核验", 500
        ) from error
    return saved
