"""Pure projections from verified native records; no inferred current run or score."""

from copy import deepcopy
from datetime import datetime

from packages.contracts import work_context_api as contract
from packages.domain import package_scope_review as review
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


def fail(code, message, status=409):
    raise DomainError("WORK_CONTEXT_" + code, message, status)


def check(condition, message="所选记录与原生身份或证明不能一致核验"):
    if not condition:
        fail("CORRUPT", message, 500)


def validated(name, value):
    check(contract.valid(name, value), "只读工作上下文投影不能通过封闭协议核验")
    return value


def package_target(value):
    m = value["manifest"]
    return {
        "kind": "package_revision",
        "bid_id": m["scope"]["bid_id"],
        "package_id": m["package_id"],
        "revision_id": m["revision_id"],
        "package_digest": value["digest"],
    }


def run_selection(run, selected):
    target = package_target(selected["target"])
    value = {
        **target,
        "kind": "package_review_run",
        "inventory_id": selected["inventory"]["manifest"]["id"],
        "inventory_digest": selected["inventory"]["digest"],
        **{
            key: run[key]
            for key in (
                "frozen_input_id",
                "frozen_input_digest",
                "execution_input_id",
                "execution_input_digest",
                "dependency_plan_id",
                "dependency_plan_digest",
                "input_digest",
                "method_digest",
            )
        },
        "run_id": run["id"],
        "result_digest": run["result"]["digest"] if run["result"] else None,
    }
    return validated("WorkContextRunSelection", value)


def run_target(selection):
    keys = contract.RUN_TARGET["properties"]
    return {key: deepcopy(selection[key]) for key in keys}


def dimension(status, reason, selected=None, observed=None):
    return {
        "status": status,
        "selected_digest": selected,
        "observed_digest": observed,
        "reason": reason,
    }


def compare(selected, observed, *, reason="EXACT_VALUE_MATCH", missing="CURRENT_RECORD_MISSING"):
    if observed is None:
        return dimension("unknown", missing, digest(selected) if selected is not None else None)
    return dimension(
        "matched" if selected == observed else "changed",
        reason if selected == observed else "EXACT_VALUE_CHANGED",
        digest(selected),
        digest(observed),
    )


def effective_sources(rows, at):
    """Only the source metadata visible in this snapshot; no original-byte claim."""
    moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    try:
        return bool(rows) and all(
            row["policy_class"] == "prebid_content"
            and row["status"] == "published"
            and row["known_at"] is not None
            and row["valid_from"] is not None
            and datetime.fromisoformat(row["known_at"]) <= moment
            and datetime.fromisoformat(row["valid_from"]) <= moment
            and (row["valid_until"] is None or moment < datetime.fromisoformat(row["valid_until"]))
            for row in rows
        )
    except (TypeError, KeyError, ValueError):
        return False


def review_summary(run, payload, human):
    """Derive counts from all exact rows and verify their original definition/range.

    Native JSONB checksums alone do not prove an aggregate. Rebuilding the result
    envelope also rejects re-sealed counts, coverage, documents and limitations.
    Human opinions remain a separate current observation of this exact result.
    """
    result = run["result"]
    if result is None:
        check(human is None)
        return None
    m = result["manifest"]
    rows = m["matrix"]
    requirements = {row["requirement_id"]: row for row in payload["requirements"]}
    by_id = {row["requirement_id"]: row for row in rows}
    check(
        len(requirements) == len(payload["requirements"])
        and len(by_id) == len(rows)
        and set(requirements) == set(by_id),
        "核查矩阵存在重复、缺失或不属于原清单的要求",
    )
    for item in rows:
        original = requirements[item["requirement_id"]]
        expected = {
            "requirement_digest": original["requirement_digest"],
            "rule_digest": original["rule_digest"],
            "rule_kind": original["rule"]["kind"],
            "requirement_statement": original["rule"]["statement"],
            "applicability": original["requirement"]["applicability"],
            "target_part_ids": original["requirement"]["target_part_ids"],
            "inspected_ranges": [
                {
                    "member_id": document["member_id"],
                    "document_version_id": document["document_version_id"],
                    "parse_run_id": document["parse_run_id"],
                    **part,
                }
                for document in payload["documents"]
                if document["package_role"] == "target"
                for part in document["parts"]
                if part["part_id"] in original["requirement"]["target_part_ids"]
            ],
        }
        check(all(item[key] == value for key, value in expected.items()))
    # The only input fields used by result_manifest are immutable run identity.
    input_manifest = {
        "scope": run["scope"],
        "execution_input": {
            "id": run["execution_input_id"],
            "digest": run["execution_input_digest"],
            "identity": {"execution_digest": run["execution_digest"]},
        },
        "dependency_plan": {
            "id": run["dependency_plan_id"],
            "digest": run["dependency_plan_digest"],
        },
        "executor_method": {"digest": run["method_digest"]},
    }
    rebuilt = review.result_manifest(run["id"], input_manifest, payload, rows)
    rebuilt["input_digest"] = run["input_digest"]
    check(
        rebuilt == m and digest(m) == result["digest"], "原报告聚合、覆盖或提交文件与完整矩阵不一致"
    )
    check(
        human is not None
        and human["scope"] == run["scope"]
        and human["run_id"] == run["id"]
        and human["result_digest"] == result["digest"]
        and human["frozen_input_id"] == run["frozen_input_id"]
        and human["execution_input_id"] == run["execution_input_id"]
        and len(human["items"]) == len(rows)
        and {item["requirement_id"] for item in human["items"]} == set(by_id)
        and all(
            item["row_digest"] == digest(by_id[item["requirement_id"]]) for item in human["items"]
        ),
        "当前人工意见未完整绑定同一运行、原结果和要求行",
    )
    counts = dict.fromkeys(contract.HUMAN_STATES, 0)
    for item in human["items"]:
        state = item["current"]["state"] if item["current"] else "unreviewed"
        check(state in counts)
        counts[state] += 1
    return validated(
        "WorkContextReviewSummary",
        {
            "run_id": run["id"],
            "input_digest": run["input_digest"],
            "result_digest": result["digest"],
            "requirement_count": len(rows),
            "machine_counts": {
                verdict: sum(row["verdict"] == verdict for row in rows)
                for verdict in contract.VERDICTS
            },
            "human_counts": counts,
            "human_heads_digest": digest(human),
            "human_basis": "current_heads_for_exact_result",
            "matrix_coverage": m["matrix_coverage"],
            "overall_coverage": "partial",
            "inventory_complete": False,
            "quality_status": "not_measured",
            "risk_resolution_assessed": False,
        },
    )


def context(selection, identity, state, observations, summary, targets, observed_at):
    value = {
        "version": "package-work-context/1",
        "selection": selection,
        "selection_digest": digest(selection),
        "identity": identity,
        "state": state,
        "current_observation": observations,
        "summary": summary,
        "native_targets": targets,
        "original_bytes_reverified": False,
        "limitations": [
            "DECLARED_SCOPE_ONLY",
            "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
            "WHOLE_PACKAGE_RISK_NOT_ASSESSED",
            "FORMAL_SCORING_SCOPE_NOT_SELECTED",
            "OFFICIAL_LABELS_NOT_READ",
            "ORIGINAL_BYTES_NOT_REVERIFIED",
            "READ_CONTEXT_IS_NOT_WRITE_AUTHORITY",
        ],
    }
    # Wall-clock time is displayed, but excluded from the content marker: a read
    # of unchanged data does not invalidate a pagination observation by itself.
    value["observation_digest"] = digest(value)
    value["observed_at"] = observed_at
    return validated("PackageWorkContext", value)


def submission_review(saved_run, current_summary):
    """Only a result already bound by registration may supply its review summary."""
    if saved_run is None or saved_run["result"] is None:
        return None
    check(
        current_summary is not None
        and current_summary["run_id"] == saved_run["id"]
        and current_summary["input_digest"] == saved_run["input_digest"]
        and current_summary["result_digest"] == saved_run["result"]["digest"],
        "实交摘要不能使用未绑定或另一次核查的结果",
    )
    return deepcopy(current_summary)


def summary(review_result, *, submission=False, bound_missing=False, changed=False):
    return {
        "perspective": "submission_history" if submission else "declared_scope_history",
        "review_status": "result_available"
        if review_result
        else "bound_result_missing"
        if bound_missing
        else "not_selected"
        if submission
        else "run_unfinished",
        "review": review_result,
        "whole_package_blocking_risk_count": None,
        "whole_package_passed": None,
        "formal_scoring": {
            "status": "scope_not_selected",
            "scope_id": None,
            "numeric_prediction": None,
        },
        "official_labels_read": False,
        "primary_action": "inspect_changed_basis"
        if changed
        else "open_selected_submission"
        if submission
        else "open_selected_review"
        if review_result
        else "view_selected_operation",
        "action_mode": "navigation_only",
    }
