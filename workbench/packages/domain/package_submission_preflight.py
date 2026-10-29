"""Read exact submission originals off-transaction, then repeat every observation.

The returned receipt describes this observation only. It is not a stored grant,
does not create a submission, and cannot replace the native registration checks.
"""

from copy import deepcopy

from packages.contracts.package_submissions_api import validate
from packages.domain import bid_package_scope_review as review_admission
from packages.domain import bid_package_submission_observations as observations
from packages.domain import bid_package_submission_repository as repository
from packages.domain import original_verification
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import ROOT, DomainError, connection, sha

VERSION = "package-submission-preflight/1"
MAX_ORIGINAL_BYTES = 8 * 1024 * 1024 * 1024
POLICY_FILES = (
    "packages/domain/package_submission_preflight.py",
    "packages/domain/bid_package_submission_observations.py",
    "packages/domain/package_submission_gate.py",
    "packages/domain/bid_package_scope_review.py",
    "packages/domain/original_verification.py",
    "packages/contracts/package_submissions_api.py",
)


def _failure(code, message, status=409):
    raise DomainError("PACKAGE_SUBMISSION_PREFLIGHT_" + code, message, status)


def _policy():
    return digest(
        {
            "version": VERSION,
            "max_original_bytes": MAX_ORIGINAL_BYTES,
            "sources": {path: sha((ROOT / path).read_bytes()) for path in POLICY_FILES},
        }
    )


def _runtime(c, value):
    run = value["review_run"]
    if run is None:
        return {
            "state": "not_selected",
            "run_id": None,
            "selected_input_digest": None,
            "current_input_digest": None,
            "codes": ["PACKAGE_REVIEW_NOT_SELECTED"],
        }
    result = {
        "state": "blocked",
        "run_id": run["id"],
        "selected_input_digest": run["input_digest"],
        "current_input_digest": None,
        "codes": ["PACKAGE_REVIEW_NOT_SUCCEEDED"],
    }
    if run["operation"]["state"] != "succeeded" or run["result"] is None:
        return result
    scope = tuple(
        run["scope"][key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
    )
    request = {
        "execution_input_digest": run["execution_input_digest"],
        "dependency_plan_id": run["dependency_plan_id"],
        "dependency_plan_digest": run["dependency_plan_digest"],
    }
    try:
        # This API-side observer does not obtain a provider client or enqueue work.
        current = review_admission._observe(
            c, scope, run["frozen_input_id"], run["execution_input_id"], request, worker=False
        )
        current_digest = digest(current.input_manifest())
    except DomainError as error:
        # Corruption and service failures remain failures, not a friendly blocked card.
        if error.status not in {404, 409, 422}:
            raise
        return result | {"codes": [error.code]}
    if current_digest != run["input_digest"]:
        return result | {
            "current_input_digest": current_digest,
            "codes": ["PACKAGE_REVIEW_RUNTIME_INPUT_CHANGED"],
        }
    return result | {"state": "matched", "current_input_digest": current_digest, "codes": []}


def _capture(scope, body, condition, bid_etag_fn):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        repository.require_schema(c)
        etag = bid_etag_fn(c, scope[0])
        if condition != etag:
            raise DomainError("REVISION_CONFLICT", "项目已变化，请重新读取提交检查", 412)
        value = observations.observe(c, scope, body["selection"])
        if value["input_digest"] != body["input_digest"]:
            _failure("INPUT_CHANGED", "所选包、清单、来源、确认或历史风险已变化，请重新读取检查")
        total = sum(row["byte_size"] for row in value["originals"])
        if total > MAX_ORIGINAL_BYTES:
            _failure(
                "CAPACITY_EXCEEDED", "整包原件与来源祖先超过本次完整核验容量，未截断任何文件", 422
            )
        return {
            "value": value,
            "etag": etag,
            "runtime": _runtime(c, value),
            "policy_digest": _policy(),
        }


def _stable(captured):
    value = captured["value"]
    return {
        "input_digest": value["input_digest"],
        "originals": value["originals"],
        # Validity intervals can expire without a row mutation or a new bid ETag.
        "gate": {
            key: field for key, field in value["gate"]["manifest"].items() if key != "checked_at"
        },
        "runtime": captured["runtime"],
        "etag": captured["etag"],
        "policy_digest": captured["policy_digest"],
    }


def _view(captured, actor):
    value, runtime = captured["value"], captured["runtime"]
    gate = deepcopy(value["gate"]["manifest"])
    current = gate["gates"]["current_input"]
    codes = set(current["codes"]) - {
        "ORIGINAL_BYTES_NOT_CHECKED",
        "REVIEW_RUNTIME_DEPENDENCIES_NOT_CHECKED",
    }
    codes.update(runtime["codes"])
    # Existing metadata blockers retain their original severity. Runtime changes
    # block the current-input check; an unselected review leaves it unknown.
    state = current["state"]
    if state != "blocked":
        state = "blocked" if runtime["state"] == "blocked" else "unknown" if codes else "pass"
    public = [observations.public_original(row) for row in value["originals"]]
    verified_input = {
        "state": state,
        "codes": sorted(codes),
        "scope": "current_input_verified_observation",
        "metadata_observations_digest": current["observations_digest"],
        "current_identity_digest": current["current_identity_digest"],
        "original_verification": "verified_at_observation",
        "original_count": len(public),
        "originals_digest": digest(public),
        "physical_page_gaps": current["physical_page_gaps"],
    }
    manifest = {
        "version": VERSION,
        "kind": "verified_package_submission_observation",
        "subject": gate["subject"],
        "selection_request": value["selection_request"],
        "selection_digest": digest(value["selection"]),
        "input_digest": value["input_digest"],
        "actor_id": actor,
        "checked_at": value["observed_at"],
        "bid_etag": captured["etag"],
        "policy_digest": captured["policy_digest"],
        "metadata_gate_digest": value["gate"]["digest"],
        "review_runtime": runtime,
        "originals": public,
        "gates": gate["gates"] | {"current_input": verified_input},
        "state": "blocked" if state == "blocked" or gate["state"] == "blocked" else "unknown",
        "allowed": False,
        "inventory_complete": False,
        "quality_status": "not_measured",
        "submission_eligible": False,
        "publication_authorized": False,
        "platform_submission_verified": False,
        "limitations": [
            "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
            "PACKAGE_REVIEW_QUALITY_NOT_MEASURED",
            "HUMAN_OPINION_IS_NOT_RECHECK_RESOLUTION",
            "ORIGINAL_BYTES_VERIFIED_AT_OBSERVATION_ONLY",
            "ORIGINAL_BYTES_NOT_ATOMIC_WITH_DATABASE",
            "PREFLIGHT_IS_NOT_SUBMISSION_AUTHORIZATION",
        ],
    }
    result = {"manifest": manifest, "digest": digest(manifest)}
    validate("PackageSubmissionPreflightView", result)
    return result


def inspect(scope, actor, body, condition, *, bid_etag_fn, final_auth):
    """A fresh authenticated read; no grant, storage write, model call or task."""
    validate("PackageSubmissionPreflightRequest", body)
    if not condition:
        raise DomainError("PRECONDITION_REQUIRED", "请提供提交检查的当前强 ETag", 428)
    scope, actor, body = tuple(map(str, scope)), str(actor), deepcopy(body)
    before = _capture(scope, body, condition, bid_etag_fn)
    # All DB sessions are closed before the first object read. Ancestors are
    # verified too; the receipt exposes neither storage locators nor file bytes.
    for row in before["value"]["originals"]:
        original_verification.verify(row)
    if str(final_auth()) != actor:
        _failure("ACTOR_CHANGED", "原件核验期间当前账户发生变化，复核结果未发布", 403)
    after = _capture(scope, body, condition, bid_etag_fn)
    if canonical(_stable(before)) != canonical(_stable(after)):
        _failure("CONTEXT_CHANGED", "原件核验期间输入、来源有效期、评审依赖或历史风险已变化")
    return _view(after, actor)
