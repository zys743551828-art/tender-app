"""Six ordered navigation groups from a verified exact run and one read observation."""

from packages.contracts import package_next_actions as contract
from packages.contracts import package_review_decisions_api as decisions_contract
from packages.contracts import package_review_runs_api as runs_contract
from packages.contracts import work_context_api as context_contract
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from packages.work_contexts import policy as context_policy

CRITICAL = {"disqualification", "mandatory"}
OPEN = {"violated", "not_found", "unable_to_judge"}
REQUIRED = (
    "identity",
    "package_head",
    "authority_head",
    "inventory_head",
    "rule_set_head",
    "sources",
    "executor_method",
)
DIMENSION_NAMES = {
    "identity": "主体与工程身份",
    "package_head": "投标包修订",
    "authority_head": "招标依据包修订",
    "inventory_head": "要求清单",
    "rule_set_head": "规则版本",
    "sources": "来源当前效力",
    "selected_facts": "所选事实",
    "executor_method": "核查方法",
    "submission_head": "实交记录头",
    "review_run_head": "核查当前记录头",
    "bound_run_state": "所绑定核查状态",
}


def require(condition):
    if not condition:
        raise DomainError(
            "PACKAGE_NEXT_ACTION_BASIS_INVALID", "下一步必须绑定完整所选运行与本次观察", 500
        )


def binding(run):
    return {
        "scope": run["scope"],
        "run_id": run["id"],
        "result_digest": run["result"]["digest"] if run["result"] else None,
        **{
            key: run[key]
            for key in (
                "input_digest",
                "frozen_input_id",
                "frozen_input_digest",
                "execution_input_id",
                "execution_input_digest",
                "dependency_plan_id",
                "dependency_plan_digest",
                "method_digest",
            )
        },
    }


def make(
    run,
    payload,
    human,
    observations,
    *,
    phase,
    archived_at,
    accept_rules_as_written,
    confirmations,
    confirmation_digest,
    method_digest,
    observed_at,
):
    require(runs_contract.valid("PackageReviewRunView", run))
    require((run["operation"]["state"] == "succeeded") == (run["result"] is not None))
    require(
        human is None
        if run["result"] is None
        else decisions_contract.valid("PackageReviewHumanDecisionCurrent", human)
    )
    # Rebuild all original counts/rows and check every current human head. A
    # confirmed human opinion never changes the machine verdict or resolves risk.
    summary = context_policy.review_summary(run, payload, human)
    require(
        set(observations) == set(context_contract.DIMENSIONS)
        and all(
            context_contract.valid("WorkContextDimensionObservation", value)
            for value in observations.values()
        )
    )
    require(
        phase in {"preparation", "working", "submitted", "closed", "terminated"}
        and type(accept_rules_as_written) is bool
    )
    critical_rules = {
        row["requirement_id"] for row in payload["requirements"] if row["rule"]["kind"] in CRITICAL
    }
    require(
        set(confirmations) == critical_rules
        and all(
            value in {"pending", "confirmed", "rejected", "deferred", "unknown"}
            for value in confirmations.values()
        )
    )
    pending = (
        set()
        if accept_rules_as_written
        else {key for key, value in confirmations.items() if value != "confirmed"}
    )
    rows = run["result"]["manifest"]["matrix"] if run["result"] else []
    critical = {
        row["requirement_id"]
        for row in rows
        if row["rule_kind"] in CRITICAL and row["verdict"] in OPEN
    }
    suggestions = {
        row["requirement_id"]
        for row in rows
        if row["rule_kind"] not in CRITICAL and row["verdict"] in OPEN
    }
    historical = {"critical": len(critical), "suggestions": len(suggestions)} if summary else None
    if archived_at is not None or phase in {"closed", "terminated"}:
        status = "archived"
    elif any(value["status"] == "changed" for value in observations.values()):
        status = "changed"
    elif (
        (not accept_rules_as_written and "unknown" in confirmations.values())
        or any(value["status"] == "unknown" for value in observations.values())
        or any(observations[key]["status"] != "matched" for key in REQUIRED)
    ):
        status = "unknown"
    else:
        status = "matched"
    actions = []

    def add(level, key, title, identities=()):
        ordered = sorted(identities)
        actions.append(
            {
                "level": level,
                "key": key,
                "title": title,
                "requirement_ids": ordered,
                "item_count": len(ordered) if ordered else None,
            }
        )

    if status == "archived":
        add(1, "view_archived_run", "查看已结束项目的所选核查历史")
    elif status == "changed":
        add(1, "inspect_changed_basis", "本轮依据已变化，先核对确切输入与新一轮位置")
    elif status == "unknown":
        add(1, "inspect_unknown_basis", "本次依据尚不能完整核验，先检查缺口")
    elif run["operation"]["state"] in {"failed", "cancelled"}:
        add(2, "inspect_failed_run", "查看本次未完成的核查与原因，再明确决定是否重试")
    elif summary is None:
        add(2, "observe_run", "所选核查尚在处理，查看这一运行的真实进度")
    else:
        gaps = {row["requirement_id"] for row in rows if row["verdict"] == "unable_to_judge"}
        if gaps:
            add(2, "inspect_coverage_gaps", "核对本轮无法判断的要求与覆盖缺口", gaps)
        if critical:
            add(3, "inspect_critical_risks", "处理已选范围内的否决或强制要求问题", critical)
        if pending:
            add(4, "confirm_critical_rules", "核对本次仍待确认的关键规则", pending)
        scoring = {
            row["requirement_id"]
            for row in rows
            if row["rule_kind"] == "scoring" and row["verdict"] in OPEN
        }
        if scoring:
            add(5, "inspect_scoring_scope", "核对评分条款与改稿依据；本轮不提供正式预测分", scoring)
        advisory = suggestions - scoring
        if advisory:
            add(6, "inspect_advisories", "查看已选范围中的其他建议", advisory)
        if not actions:
            add(6, "inspect_package_limitations", "检查整包清单与未覆盖范围，不据此认定可以提交")
    primary = actions[0]
    assigned = set(primary["requirement_ids"])
    others = []
    for action in actions[1:]:
        remaining = sorted(set(action["requirement_ids"]) - assigned)
        if remaining:
            others.append({**action, "requirement_ids": remaining, "item_count": len(remaining)})
            assigned.update(remaining)
    countable = status == "matched" and summary is not None
    issues = []
    for key in context_contract.DIMENSIONS:
        observed = observations[key]["status"]
        if observed in {"changed", "unknown"} or (key in REQUIRED and observed == "not_applicable"):
            issue_state = "changed" if observed == "changed" else "unknown"
            issues.append(
                {
                    "dimension": key,
                    "status": issue_state,
                    "message": DIMENSION_NAMES[key]
                    + ("已变化，请核对本次选择" if issue_state == "changed" else "尚不能完整核验"),
                }
            )
    if not accept_rules_as_written and "unknown" in confirmations.values():
        issues.append(
            {
                "dimension": "critical_rule_confirmation",
                "status": "unknown",
                "message": "所选关键规则的当前确认尚不能核验",
            }
        )
    value = {
        "version": "package-next-actions/1",
        "binding": binding(run),
        "method_digest": method_digest,
        "confirmation_digest": confirmation_digest,
        "observation_digest": digest(observations),
        "basis_status": status,
        "basis_issues": issues,
        "observed_at": observed_at,
        "current_scope_counts": {**historical, "pending_critical_rules": len(pending)}
        if countable and historical is not None
        else None,
        "historical_scope_counts": historical,
        "primary": primary,
        "other_actions": others,
        "remaining_critical_count": len((critical | pending) - set(primary["requirement_ids"]))
        if countable
        else None,
        "remaining_suggestion_count": len(suggestions - set(primary["requirement_ids"]))
        if countable
        else None,
        "action_mode": "navigation_only",
        "perspective": "selected_declared_scope",
        **dict.fromkeys(
            (
                "original_bytes_reverified",
                "inventory_complete",
                "formal_scoring_eligible",
                "submission_eligible",
            ),
            False,
        ),
    }
    value["basis_digest"] = digest(
        {
            "binding": value["binding"],
            "method_digest": method_digest,
            "observation_digest": value["observation_digest"],
            "human": human,
            "confirmations": confirmations,
            "confirmation_digest": confirmation_digest,
            "phase": phase,
            "archived_at": archived_at,
            "accept_rules_as_written": accept_rules_as_written,
        }
    )
    contract.validate(value)
    return value
