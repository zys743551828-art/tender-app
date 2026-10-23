"""Pure directory observations; registered packages never imply current review qualification."""

from packages.contracts.project_summary_api import validate
from packages.domain.runtime import DomainError, clean


def project(row):
    if row["invalid_heads"]:
        raise DomainError(
            "PROJECT_SUMMARY_PACKAGE_HEAD_INVALID", "资料包目录身份异常，请重新核对", 409
        )
    bid = str(row["id"])
    archived = row["archived_at"] is not None or row["phase"] in {"closed", "terminated"}
    if archived:
        action = ("view_history", "查看已结束项目的稿件与阶段记录", "work-context", True)
    elif not row["authority_count"] or not row["bid_count"]:
        action = ("assemble_packages", "登记并核对本次招标依据包和投标包", "packages", False)
    elif row["not_frozen_members"]:
        action = ("inspect_package_parses", "核对资料包中尚未冻结的解析身份", "packages", True)
    else:
        action = (
            "choose_package_revision",
            "选择确切包修订，继续核对要求与结果",
            "packages",
            False,
        )
    value = {
        "bid_id": bid,
        "phase": row["phase"],
        "archived_at": clean(row["archived_at"]),
        "package_counts": {"authority": row["authority_count"], "bid": row["bid_count"]},
        "head_members": {
            "total": row["member_count"],
            "parse_not_frozen": row["not_frozen_members"],
        },
        "next_action": {
            "action": action[0],
            "reason": action[1],
            "target_url": f"/bids/{bid}/{action[2]}",
            "blocked": action[3],
        },
        "action_scope": "package_directory",
        "risk_status": "not_evaluated",
        "critical_risk_count": None,
        "other_risk_count": None,
        "prediction_status": "not_evaluated",
        "predicted_score": None,
        "inventory_complete": False,
        "formal_scoring_eligible": False,
        "submission_eligible": False,
    }
    validate("ProjectWorkSummary", value)
    return value
