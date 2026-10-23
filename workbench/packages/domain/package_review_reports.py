"""Deterministic report text from one immutable result and captured human heads."""

import os
from pathlib import Path

from packages.authoring.build import render_identity
from packages.contracts.package_review_reports_api import validate
from packages.domain.package_report_docx import WRITER_DIGEST, assemble_report
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha

HANDLER = "package-report/1"
STEP = "render-package-report"
KIND = "package-scope-report-start"
EVENT = "package.scope_report.started"
MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
VERDICTS = {
    "satisfied": "满足",
    "violated": "存在差异",
    "not_found": "未发现响应",
    "not_applicable": "不适用",
    "unable_to_judge": "无法判断",
}
HUMAN_STATES = {
    "confirmed": "确认此项判断",
    "rejected": "不采用此项判断",
    "needs_review": "需要复查",
}
APPLICABILITY = {"applicable": "适用", "not_applicable": "不适用", "unknown": "尚未确认"}
LIMITATIONS = {
    "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED": "尚未证明要求清单涵盖全部招标语义，仍须人工核对遗漏",
    "REQUIREMENT_APPLICABILITY_UNKNOWN": "尚未确认此要求是否适用于本次投标",
    "REQUIREMENT_TARGET_SCOPE_UNDECLARED": "此要求的待核查册页范围尚未声明",
    "FORMAL_SCORING_NOT_AVAILABLE": "当前核查不提供正式评分，此项不能据此判定得分",
    "REQUIREMENT_CHECK_UNSUPPORTED": "此要求包含当前核查尚未支持的检查条件",
    "REQUIREMENT_EFFECTIVITY_UNPROVEN": "此要求的生效条件尚未证明",
    "REQUIREMENT_VALIDITY_TIME_UNDECLARED": "此要求的适用时间尚未声明",
    "REQUIREMENT_MINIMUM_COUNT_UNKNOWN": "此要求的最低数量尚未确认",
}


def _limitations(values):
    return "；".join(LIMITATIONS.get(value, value) for value in values)


def _parts(values):
    return "；".join(
        f"{part['category']}（标识 {part['part_id']}），物理页 {part['first_page']}-{part['last_page']}"
        + ("，共享附件" if part["shared_attachment"] else "")
        + ("，目录 " + " / ".join(map(str, part["heading_path"])) if part["heading_path"] else "")
        for part in values
    )


def source_profile():
    return {
        "version": "package-review-report/1",
        "writer_digest": WRITER_DIGEST,
        "reporter_digest": sha(Path(__file__).read_bytes()),
    }


def method_profile():
    renderer, unavailable = None, None
    try:
        renderer = render_identity(
            os.environ.get("AUTHORING_RENDERER", "soffice"),
            os.environ.get(
                "AUTHORING_FONT_PATH", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            ),
        )
    except DomainError as error:
        if error.code != "RENDERER_UNAVAILABLE":
            raise
        unavailable = error.code
    return {
        **source_profile(),
        "pdf_renderer": renderer,
    }, unavailable


def binding(run):
    if run["operation"]["state"] != "succeeded" or run["result"] is None:
        raise DomainError(
            "PACKAGE_REVIEW_REPORT_NOT_READY", "核查完成并保存原报告后才能生成副本", 409
        )
    return {
        key: run[key] for key in ("scope", "frozen_input_id", "execution_input_id", "input_digest")
    } | {"run_id": run["id"], "result_digest": run["result"]["digest"]}


def context(run, human, profile, unavailable=None):
    value = {
        **binding(run),
        "human_decisions": human,
        "method": profile,
        "formal_scoring_eligible": False,
        "submission_eligible": False,
    }
    public = {
        **binding(run),
        "human_decisions_digest": digest(human),
        "method_digest": digest(profile),
        "context_digest": digest(value),
        "formats": ["docx", "pdf"] if profile["pdf_renderer"] is not None else ["docx"],
        "pdf_unavailable_code": unavailable,
        "formal_scoring_eligible": False,
        "submission_eligible": False,
    }
    validate("PackageReviewReportContext", public)
    return public, value


def freeze(context_value, format):
    if format not in MEDIA or format == "pdf" and context_value["method"]["pdf_renderer"] is None:
        raise DomainError("RENDERER_UNAVAILABLE", "当前未配置PDF转换能力，请先下载Word报告", 409)
    result = {
        "version": "package-review-report-input/1",
        "context": context_value,
        "context_digest": digest(context_value),
        "format": format,
        "artifact_kind": "review_report",
        "formal_scoring_eligible": False,
        "submission_eligible": False,
    }
    return validate("PackageReviewReportInput", result)


def check(snapshot, run):
    validate("PackageReviewReportInput", snapshot)
    value = snapshot["context"]
    if (
        any(value[key] != expected for key, expected in binding(run).items())
        or digest(value) != snapshot["context_digest"]
    ):
        raise DomainError(
            "PACKAGE_REVIEW_REPORT_CORRUPT", "报告副本与原运行、结果或输入不一致", 500
        )
    human = value["human_decisions"]
    if any(
        human[key] != value[key]
        for key in ("scope", "frozen_input_id", "execution_input_id", "run_id", "result_digest")
    ):
        raise DomainError("PACKAGE_REVIEW_REPORT_CORRUPT", "人工记录快照与原报告不一致", 500)
    originals = {row["requirement_id"]: digest(row) for row in run["result"]["manifest"]["matrix"]}
    if (
        len(human["items"]) != len(originals)
        or {row["requirement_id"]: row["row_digest"] for row in human["items"]} != originals
    ):
        raise DomainError("PACKAGE_REVIEW_REPORT_CORRUPT", "人工记录未准确绑定全部原始条款", 500)
    return snapshot


def _clean_text(value):
    return "".join(
        char
        if ord(char) >= 32 and ord(char) not in (0xFFFE, 0xFFFF) or char in "\n\t"
        else f"[U+{ord(char):04X}]"
        for char in str(value)
    )


def document(snapshot, run, *, export_id, captured_at):
    check(snapshot, run)
    result = run["result"]["manifest"]
    human = {
        row["requirement_id"]: row["current"]
        for row in snapshot["context"]["human_decisions"]["items"]
    }
    sections: list[tuple[str, list[str]]] = []

    def section(title, lines):
        sections.append((_clean_text(title), [_clean_text(line) for line in lines]))

    section(
        "投标文件范围核查报告",
        [
            "投标前辅助核对 · 部分覆盖 · 机器判断与人工意见分别记录",
            f"报告编号：{export_id}；人工记录截取时间：{captured_at}",
            f"原运行：{run['id']}；原运行时间：{run['created_at']}",
            f"项目：{run['scope']['bid_id']}；文件包：{run['scope']['package_id']}",
            "本报告记录原运行的核查结果及申请生成时的人工意见。后续来源、文件或人工意见的变化不会回写此副本。当前来源效力未在导出时重新核验。",
            "要求清单的语义完整性和真实模型效果尚未测量，不能据此认定已排除全部废标风险、获得正式评分资格或完成交易平台提交。",
            "这是评审报告副本，不是提交正文。人工‘确认此项判断’仅表示同意该判断，不代表相关风险已解决。",
            f"已列要求：{result['requirement_count']}；逐项判断：{'已覆盖已列要求' if result['matrix_coverage'] == 'complete' else '含无法判断项'}；整体覆盖：部分",
            "；".join(f"{VERDICTS[key]} {count} 项" for key, count in result["counts"].items()),
            "范围限制：" + _limitations(result["limitations"]),
        ],
    )
    section(
        "受检文件与范围",
        [
            f"{'投标响应' if item['package_role'] == 'target' else '权威依据'} · 成员 {item['member_id']}；文档版本 {item['document_version_id']}；解析版本 {item['parse_run_id']}；物理页数 {item['page_count']}；文件摘要 {item['file_digest']}；分册范围：{_parts(item['parts'])}"
            for item in result["submitted_documents"]
        ],
    )
    for number, row in enumerate(result["matrix"], 1):
        decision = human[row["requirement_id"]]
        lines = [
            row["requirement_statement"],
            f"机器判断：{VERDICTS[row['verdict']]}。{row['statement']}",
            f"适用范围：{APPLICABILITY[row['applicability']]}；目标分册标识：{'、'.join(row['target_part_ids']) or '未声明'}",
            "核查限制：" + (_limitations(row["limitations"]) or "该行未另列限制；整体仍为部分覆盖"),
            "人工意见：尚未记录"
            if decision is None
            else f"人工意见：{HUMAN_STATES[decision['state']]}。理由：{decision['reason']}；记录时间：{decision['created_at']}；操作者：{decision['actor_id']}；记录ID：{decision['id']}；摘要：{decision['digest']}",
        ]
        for title, quotes in (
            ("投标响应原页", row["target_quotes"]),
            ("权威依据原页", row["authority_quotes"]),
        ):
            if not quotes:
                lines.append(title + "：该判断未提供定位片段")
            for quote in quotes:
                lines.extend(
                    [
                        f"{title}：成员 {quote['member_id']}；文档 {quote['document_version_id']}；解析 {quote['parse_run_id']}；第 {quote['physical_page']} 物理页；分册标识 {'、'.join(quote['part_ids'])}",
                        "原文：" + quote["quote"],
                        f"证据ID：{quote['evidence_id']}；证据摘要：{quote['evidence_digest']}",
                    ]
                )
        lines.append(
            f"条款ID：{row['requirement_id']}；条款摘要：{row['requirement_digest']}；规则摘要：{row['rule_digest']}"
        )
        section(f"{number}. {VERDICTS[row['verdict']]} · 条款核对", lines)
    section(
        "版本与复查依据",
        [
            f"冻结输入：{run['frozen_input_id']}；执行准备：{run['execution_input_id']}",
            f"执行输入摘要：{run['input_digest']}；原结果摘要：{run['result']['digest']}",
            f"核查方法：{run['method_digest']}；依赖计划：{run['dependency_plan_id']}；计划摘要：{run['dependency_plan_digest']}",
            f"报告上下文：{snapshot['context_digest']}；报告输入：{digest(snapshot)}",
            "报告包含全部已列条款，没有按筛选条件省略。用于进一步复查时，应同时查看原文件版本、原页和最新人工记录。",
        ],
    )
    return assemble_report(sections)
