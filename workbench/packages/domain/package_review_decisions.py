"""Bind human opinion to one immutable machine row and its original quoted evidence."""

from copy import deepcopy

from packages.contracts.package_review_decisions_api import valid, validate
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError

KIND = "package-scope-review-human-decision"
EVENT = "package.scope_review.human_decision"
SCOPE_KEYS = ("bid_id", "package_id", "revision_id", "inventory_id")
FLAGS = ("inventory_complete", "formal_scoring_eligible", "submission_eligible")


def require(condition, code, message, status=409):
    if not condition:
        raise DomainError(code, message, status)


def request(body):
    validate("SavePackageReviewHumanDecision", body)
    require(
        bool(body["reason"].strip()),
        "PACKAGE_REVIEW_DECISION_REASON_REQUIRED",
        "请说明确认此项判断、不采用此项判断或需要复查的理由",
        422,
    )


def binding(run):
    require(
        run["result"] is not None and run["operation"]["state"] == "succeeded",
        "PACKAGE_REVIEW_RESULT_UNAVAILABLE",
        "本轮尚无已发布的核查结果，不能进行人工处置",
    )
    return {
        "scope": deepcopy(run["scope"]),
        "frozen_input_id": run["frozen_input_id"],
        "execution_input_id": run["execution_input_id"],
        "run_id": run["id"],
        "result_digest": run["result"]["digest"],
    }


def row(run, requirement_id):
    binding(run)
    matches = [
        item
        for item in run["result"]["manifest"]["matrix"]
        if item["requirement_id"] == requirement_id
    ]
    require(
        len(matches) == 1,
        "PACKAGE_REVIEW_REQUIREMENT_NOT_FOUND",
        "该核查运行中没有这条唯一的要求",
        404,
    )
    return deepcopy(matches[0])


def quotes_in_row(selected, original):
    allowed = {digest(quote) for quote in original["target_quotes"] + original["authority_quotes"]}
    return len({digest(quote) for quote in selected}) == len(selected) and all(
        digest(quote) in allowed for quote in selected
    )


def make(run, requirement_id, body, *, decision_id, actor_id, created_at, sequence_no):
    request(body)
    original = row(run, requirement_id)
    require(
        body["result_digest"] == run["result"]["digest"] and body["row_digest"] == digest(original),
        "PACKAGE_REVIEW_DECISION_BASIS_CHANGED",
        "人工处置绑定的报告或条款摘要不同，请重新读取原结果",
    )
    require(
        quotes_in_row(body["selected_quotes"], original),
        "PACKAGE_REVIEW_DECISION_EVIDENCE_INVALID",
        "只能选择本条机器原结果已引用的完整证据，不可新增、改写或串用其他条款引用",
        422,
    )
    manifest = {
        "version": "package-review-human-decision/1",
        "id": decision_id,
        "actor_id": actor_id,
        "created_at": created_at,
        "sequence_no": sequence_no,
        **binding(run),
        "requirement_id": requirement_id,
        "input_digest": run["input_digest"],
        "row_digest": body["row_digest"],
        "previous_head": deepcopy(body["expected_head"]),
        "state": body["state"],
        "reason": body["reason"],
        "selected_quotes": deepcopy(body["selected_quotes"]),
        **dict.fromkeys(FLAGS, False),
    }
    value = {"manifest": manifest, "digest": digest(manifest)}
    check(value, run, requirement_id)
    return value


def check(value, run, requirement_id=None):
    try:
        if not valid("PackageReviewHumanDecisionView", value):
            raise ValueError("contract")
        manifest = value["manifest"]
        actual_id = manifest["requirement_id"]
        original = row(run, actual_id)
        if (
            digest(manifest) != value["digest"]
            or any(manifest[key] != field for key, field in binding(run).items())
            or manifest["input_digest"] != run["input_digest"]
            or manifest["row_digest"] != digest(original)
            or (requirement_id is not None and requirement_id != actual_id)
            or not manifest["reason"].strip()
            or not quotes_in_row(manifest["selected_quotes"], original)
            or (manifest["sequence_no"] == 1) != (manifest["previous_head"] is None)
        ):
            raise ValueError("binding")
        return deepcopy(value)
    except (KeyError, ValueError, TypeError, DomainError) as error:
        raise DomainError(
            "PACKAGE_REVIEW_DECISION_CORRUPT", "人工处置记录与其原报告、条款或引用无法一致核验", 500
        ) from error


def assert_scope(value, scope, frozen_id, prepared_id, run_id, requirement_id):
    manifest = value["manifest"]
    require(
        tuple(manifest["scope"][key] for key in SCOPE_KEYS) == scope
        and manifest["frozen_input_id"] == frozen_id
        and manifest["execution_input_id"] == prepared_id
        and manifest["run_id"] == run_id
        and manifest["requirement_id"] == requirement_id,
        "PACKAGE_REVIEW_DECISION_NOT_FOUND",
        "该核查条款下没有这条人工处置回执",
        404,
    )
