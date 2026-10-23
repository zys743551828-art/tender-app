"""Deterministic retrospective policy; user hypotheses never become official findings."""

from copy import deepcopy

from packages.contracts import package_retrospectives_api as contract
from packages.domain.review_identity import canonical
from packages.domain.runtime import DomainError, sha

FLAGS = dict.fromkeys(contract.FLAGS, False)


def fail(code, message, status=409):
    raise DomainError("PACKAGE_RETROSPECTIVE_" + code, message, status)


def selection(value):
    contract.validate("PackageRetrospectiveSelection", value)
    for key in ("outcome", "business_result"):
        if (value[key + "_id"] is None) != (value[key + "_missing_reason"] is not None):
            fail("MISSING_REASON", "未选择结果时请说明待补资料；选择记录后不能同时声明缺失", 422)
    left, right = value["baseline_run_id"], value["submitted_run_id"]
    if (left is None) != (right is None) or (left is None) != (
        value["reviews_missing_reason"] is not None
    ):
        fail("REVIEW_PAIR_REQUIRED", "请明确选择两条核查，或说明两轮核查待补原因", 422)
    if left is not None and left == right:
        fail("SAME_RUN", "两轮差异需要两条不同的已完成核查", 422)
    return deepcopy(value)


def packet(manifest, name):
    result = {"manifest": deepcopy(manifest), "digest": sha(manifest)}
    if len(canonical(result)) > contract.LIMITS["snapshot_bytes"]:
        fail("CAPACITY_EXCEEDED", "复盘依据超过容量，未截断原始差异或来源", 413)
    if not contract.valid(name, result):
        fail("CORRUPT", "复盘身份或来源快照不能一致核验", 500)
    return result


def check_packet(value, name):
    if not contract.valid(name, value) or sha(value["manifest"]) != value["digest"]:
        fail("CORRUPT", "已存复盘快照或摘要不能一致核验", 500)
    if name == "PackageRetrospectiveView":
        check_packet(value["manifest"]["preview"], "PackageRetrospectivePreview")
    return value


def knowledge_content(frozen):
    """Only recorded facts and attributed notes. No model, deductions or score conversion."""
    check_packet(frozen, "PackageRetrospectiveView")
    m = frozen["manifest"]
    p = m["preview"]["manifest"]
    s, outcome, result, comparison = (
        p["submission"],
        p["outcome"],
        p["business_result"],
        p["comparison"],
    )
    lines = [
        "待核复盘候选（事后资料）",
        f"原实交：{s['id']}；包修订：{s['revision_id']}；提交时间：{s['submitted_at']}。",
        "本记录只保留所选依据及成员意见，不确认逐项扣分原因、风险已解决或研究资格。",
    ]
    if outcome:
        lines.append(
            f"所选官方成绩：{outcome['score_kind']}；分数：{outcome['value'] if outcome['value'] is not None else '未知'}；满分：{outcome['maximum'] if outcome['maximum'] is not None else '未知'}；核验状态：{outcome['verification']}。"
        )
        lines.append("现有成绩类型没有逐项扣分依据，不能从总分反推扣分条款或原因。")
    if result:
        lines.append(
            f"所选业务阶段：{result['stage']}；来源类型：{result['source_type']}；核验状态：{result['verification']}。"
        )
    if comparison:
        counts = comparison["manifest"]["counts"]
        lines.append("两轮核查只报告原要求及判断差异；人工处置仍为成员意见。")
        lines.append(
            f"要求新增 {counts['added']}，移除 {counts['removed']}，定义变更 {counts['changed']}；判断变化 {counts['verdict_changed']}。"
        )
    for title, field in (
        ("成员记录的观察（待核）", "observations"),
        ("成员假设（尚无结论）", "hypotheses"),
        ("下一步核对和整改", "next_actions"),
        ("成员补充的待补资料", "additional_missing_materials"),
    ):
        if m["notes"][field].strip():
            lines.extend((title + "：", m["notes"][field]))
    if p["gaps"]:
        lines.extend(("系统识别的资料或资格缺口：", *["- " + gap["message"] for gap in p["gaps"]]))
    lines.append(f"不可变来源：复盘 {m['id']}，摘要 {frozen['digest']}。")
    return "\n\n".join(lines)
