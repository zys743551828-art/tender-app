"""Exact, deterministic row comparison. Text similarity never establishes requirement identity."""

from copy import deepcopy

from packages.contracts.package_review_comparisons_api import COUNT_FIELDS, ROW_FIELDS, valid
from packages.domain import package_scope_review as review
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


def require(condition, code, message, status=409):
    if not condition:
        raise DomainError(code, message, status)


def _verify_side(side):
    try:
        run, packet, human = side["run"], side["input"], side["human"]
        if not valid("PackageReviewRunView", run):
            raise ValueError("run contract")
        require(
            run["operation"]["state"] == "succeeded" and run["result"] is not None,
            "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED",
            "只能对比两条已完成且已发布原结果的核查运行",
        )
        if set(packet) != {"manifest", "digest"}:
            raise ValueError("input packet")
        manifest = packet["manifest"]
        review.validate_input(manifest)
        expected = {
            "scope": manifest["scope"],
            "frozen_input_id": manifest["frozen_input"]["id"],
            "frozen_input_digest": manifest["frozen_input"]["digest"],
            "execution_input_id": manifest["execution_input"]["id"],
            "execution_input_digest": manifest["execution_input"]["digest"],
            "execution_digest": manifest["execution_input"]["identity"]["execution_digest"],
            "dependency_plan_id": manifest["dependency_plan"]["id"],
            "dependency_plan_digest": manifest["dependency_plan"]["digest"],
            "method_digest": manifest["executor_method"]["digest"],
        }
        if (
            packet["digest"] != digest(manifest)
            or run["input_digest"] != packet["digest"]
            or run["operation"]["input_digest"] != packet["digest"]
            or any(run[key] != value for key, value in expected.items())
        ):
            raise ValueError("input binding")
        result = run["result"]["manifest"]
        review.validate_contract("Result", result)
        if (
            digest(result) != run["result"]["digest"]
            or result["run_id"] != run["id"]
            or result["bid_id"] != run["scope"]["bid_id"]
            or result["input_digest"] != run["input_digest"]
            or any(
                result[key] != value
                for key, value in expected.items()
                if key not in {"frozen_input_id", "frozen_input_digest"}
            )
        ):
            raise ValueError("result binding")
        rows = {row["requirement_id"]: row for row in result["matrix"]}
        if len(rows) != result["requirement_count"] or len(rows) != len(result["matrix"]):
            raise ValueError("duplicate or incomplete matrix")
        if (
            not valid("PackageReviewHumanDecisionCurrent", human)
            or human["scope"] != run["scope"]
            or human["run_id"] != run["id"]
            or human["frozen_input_id"] != run["frozen_input_id"]
            or human["execution_input_id"] != run["execution_input_id"]
            or human["result_digest"] != run["result"]["digest"]
            or {item["requirement_id"] for item in human["items"]} != set(rows)
            or len(human["items"]) != len(rows)
            or any(
                item["row_digest"] != digest(rows[item["requirement_id"]])
                for item in human["items"]
            )
        ):
            raise ValueError("human head binding")
        return rows
    except (KeyError, TypeError, ValueError, DomainError) as error:
        if (
            isinstance(error, DomainError)
            and error.code == "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED"
        ):
            raise
        raise DomainError(
            "PACKAGE_REVIEW_COMPARISON_CORRUPT",
            "对比所选运行、原结果或人工处置摘要无法一致核验",
            500,
        ) from error


def _run_summary(side):
    run, human = side["run"], side["human"]
    return {
        **{
            key: deepcopy(run[key])
            for key in (
                "id",
                "actor_id",
                "created_at",
                "scope",
                "frozen_input_id",
                "frozen_input_digest",
                "execution_input_id",
                "execution_input_digest",
                "execution_digest",
                "input_digest",
                "method_digest",
                "dependency_plan_id",
                "dependency_plan_digest",
            )
        },
        "result_digest": run["result"]["digest"],
        **{
            key: run["result"]["manifest"][key]
            for key in ("requirement_count", "matrix_coverage", "overall_coverage")
        },
        "human_heads_digest": digest(human),
    }


def _definition(row):
    return row["requirement_digest"], row["rule_digest"]


def _changes(left, right, left_rows, right_rows):
    a, b = left["input"]["manifest"], right["input"]["manifest"]
    ap, bp = a["executor_method"]["profile"], b["executor_method"]["profile"]
    return {
        "run_input": left["input"]["digest"] != right["input"]["digest"],
        "scope": a["scope"] != b["scope"],
        "frozen_input": a["frozen_input"] != b["frozen_input"],
        "prepared_input": {key: a["execution_input"][key] for key in ("id", "digest")}
        != {key: b["execution_input"][key] for key in ("id", "digest")},
        "rerun_intent": a["execution_input"]["identity"]["rerun"]
        != b["execution_input"]["identity"]["rerun"],
        "requirements": {key: _definition(row) for key, row in left_rows.items()}
        != {key: _definition(row) for key, row in right_rows.items()},
        "submitted_documents": left["run"]["result"]["manifest"]["submitted_documents"]
        != right["run"]["result"]["manifest"]["submitted_documents"],
        "selected_facts": a["selected_facts_digest"] != b["selected_facts_digest"],
        "fact_admission": a["fact_admission"] != b["fact_admission"],
        "dependency_plan": a["dependency_plan"] != b["dependency_plan"],
        "inventory_proof": a["inventory_proof_digest"] != b["inventory_proof_digest"],
        "method": a["executor_method"]["digest"] != b["executor_method"]["digest"],
        "method_fields": sorted(key for key in ap.keys() | bp.keys() if ap.get(key) != bp.get(key)),
    }


def _row_summary(row):
    if row is None:
        return None
    return {"row_digest": digest(row), **{key: deepcopy(row[key]) for key in ROW_FIELDS}}


def compare(bid_id, left, right):
    left_rows, right_rows = _verify_side(left), _verify_side(right)
    require(
        left["run"]["scope"]["bid_id"] == right["run"]["scope"]["bid_id"] == bid_id,
        "PACKAGE_REVIEW_COMPARISON_RUN_NOT_FOUND",
        "该标段下没有所选的两条核查运行",
        404,
    )
    require(
        left["run"]["id"] != right["run"]["id"],
        "PACKAGE_REVIEW_COMPARISON_SAME_RUN",
        "请明确选择两条不同的已完成核查运行",
        422,
    )
    left_human = {row["requirement_id"]: row["current"] for row in left["human"]["items"]}
    right_human = {row["requirement_id"]: row["current"] for row in right["human"]["items"]}
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    items = []
    for requirement_id in sorted(left_rows.keys() | right_rows.keys()):
        a, b = left_rows.get(requirement_id), right_rows.get(requirement_id)
        change = (
            "added"
            if a is None
            else "removed"
            if b is None
            else "unchanged"
            if _definition(a) == _definition(b)
            else "changed"
        )
        shared = a is not None and b is not None
        row_changed = digest(a) != digest(b) if shared else None
        transition = (
            {"from": a["verdict"], "to": b["verdict"], "changed": a["verdict"] != b["verdict"]}
            if shared
            else None
        )
        counts[change] += 1
        counts["machine_row_changed"] += int(row_changed is True)
        counts["verdict_changed"] += int(transition is not None and transition["changed"])
        items.append(
            {
                "requirement_id": requirement_id,
                "definition_change": change,
                "machine_row_changed": row_changed,
                "verdict_transition": transition,
                "left": _row_summary(a),
                "right": _row_summary(b),
                "left_human": deepcopy(left_human.get(requirement_id)),
                "right_human": deepcopy(right_human.get(requirement_id)),
            }
        )
    manifest = {
        "version": "package-review-comparison/1",
        "kind": "declared_scope_review_comparison",
        "bid_id": bid_id,
        "match_policy": "exact_requirement_id_and_definition_digests/1",
        "left": _run_summary(left),
        "right": _run_summary(right),
        "input_changes": _changes(left, right, left_rows, right_rows),
        "counts": counts,
        "overall_coverage": "partial",
        "risk_resolution_assessed": False,
        "inventory_complete": False,
        "formal_scoring_eligible": False,
        "submission_eligible": False,
        "items": items,
    }
    require(
        valid("PackageReviewComparisonManifest", manifest),
        "PACKAGE_REVIEW_COMPARISON_CORRUPT",
        "两轮核查对比范围或摘要无法核验",
        500,
    )
    return {"manifest": manifest, "digest": digest(manifest)}
