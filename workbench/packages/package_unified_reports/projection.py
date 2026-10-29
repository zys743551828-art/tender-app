"""Compose only verified, same-revision evidence; never invent missing checks."""

from collections import Counter
from copy import deepcopy
from pathlib import Path

from packages.domain.package_report_docx import WRITER_DIGEST, assemble_report
from packages.domain.package_review_reports import VERDICTS, _clean_text, check, freeze
from packages.domain.review_identity import digest
from packages.package_model_registry.artifact import fail
from packages.package_prediction_reports.projection import method_digest as prediction_report_method
from packages.storage.private_cas import sha

VERSION = "package-unified-review-report/1"


def method_digest():
    return digest(
        {
            "version": VERSION,
            "sources": {
                p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))
            },
            "prediction": prediction_report_method(),
            "writer": WRITER_DIGEST,
        }
    )


def compose(snapshot, prediction, identity):
    source = snapshot["packet"]["authority"]["source"]["current_source"]
    preview = source["scope_manifest"]["preview"]["manifest"]
    component = snapshot["sources"]
    run, human, settings = (component[k] for k in ("run", "human", "settings"))
    if run["scope"] != preview["scope"] or run["operation"]["state"] != "succeeded":
        fail()
    result = run["result"]["manifest"]
    if digest(result) != run["result"]["digest"]:
        fail()
    keys = ("document_version_id", "parse_run_id", "file_digest")

    def documents(rows):
        values = [tuple(r[k] for k in keys) for r in rows]
        if len(values) != len(set(values)):
            fail()
        return set(values)

    if documents(result["submitted_documents"]) != documents(preview["documents"]):
        fail()
    # Reuse the existing immutable human-head/row binding checks.
    context = {
        k: run[k] for k in ("scope", "frozen_input_id", "execution_input_id", "input_digest")
    }
    context.update(
        run_id=run["id"],
        result_digest=run["result"]["digest"],
        human_decisions=human,
        formal_scoring_eligible=False,
        submission_eligible=False,
    )
    # The original check verifies the original run and all human decisions, not a new judgement.
    from packages.domain.package_review_reports import source_profile

    context["method"] = source_profile() | {"pdf_renderer": None}
    check(freeze(context, "docx"), run)
    if (
        prediction["command_id"] != snapshot["receipt"]["command_id"]
        or prediction["input_digest"] != source["input_digest"]
    ):
        fail()
    if (prediction["state"] == "hidden") != (settings.get("show_prediction", False) is False):
        fail()
    matrix = deepcopy(result["matrix"])
    issues = [r for r in matrix if r["verdict"] in {"violated", "not_found", "unable_to_judge"}]
    pricing = component["pricing"]
    if not settings.get("pricing", True):
        if pricing is not None:
            fail()
        price = None
    elif pricing is None:
        price = {"state": "unavailable", "reason": "尚未选择同一冻结包的已完成报价模拟"}
    else:
        formula = pricing["formula_snapshot"]
        binding = formula.get("package_binding") or {}
        capsule = formula["source_authority"].get("package_snapshot") or {}
        if (
            formula["bid_id"] != preview["scope"]["bid_id"]
            or any(binding.get(k) != preview["scope"][k] for k in ("package_id", "revision_id"))
            or binding.get("authority_revision_id") != preview["basis"]["authority_revision_id"]
            or any(
                capsule.get(k) != preview["basis"][k]
                for k in (
                    "package_digest",
                    "authority_digest",
                    "inventory_digest",
                    "identity_digest",
                )
            )
            or capsule.get("inventory_id") != preview["scope"]["inventory_id"]
            or not pricing["current_applicability"]["applicable"]
        ):
            fail()
        price = {
            "state": "available",
            "simulation_id": component["simulation_id"],
            "formula_id": formula["formula_version_id"],
            "formula_digest": digest(formula),
            **{
                k: deepcopy(pricing[k])
                for k in ("candidate_price", "price_score", "maximum", "eligible", "notes")
            },
        }
    return {
        "schema": VERSION,
        "snapshot_id": identity,
        "method_digest": snapshot["method_digest"],
        "bid_id": prediction["bid_id"],
        "scope_id": prediction["scope_id"],
        "command_id": prediction["command_id"],
        "review_id": run["id"],
        "result_digest": run["result"]["digest"],
        "scope": deepcopy(run["scope"]),
        "settings": deepcopy(settings),
        "pipeline": {
            "state": "partial",
            "stale_reasons": [],
            "submission_eligible": False,
            "reason": "原整包核查覆盖仍为部分；统一报告不扩张核查或提交资格",
        },
        "requirements": [r for r in matrix if r["rule_kind"] in {"disqualification", "mandatory"}],
        "documents": deepcopy(result["submitted_documents"]),
        "matrix": matrix,
        "issues": issues,
        "issue_counts": dict(Counter(r["rule_kind"] for r in issues)),
        "unmeasured_checks": [k for k in ("consistency", "scope_residue") if settings.get(k, True)],
        "human_decisions": deepcopy(human),
        "prediction": prediction,
        "pricing": price,
        "basis_notice": "按原文接受"
        if settings.get("accept_rules_as_written", False)
        else "规则依据确认状态须按原清单核对；人工处置不等于规则确认",
    }


def sections(report):
    human = {r["requirement_id"]: r["current"] for r in report["human_decisions"]["items"]}

    def row_text(row):
        lines = [
            f"条款 {row['requirement_id']}：{row['requirement_statement']}",
            f"{VERDICTS[row['verdict']]}：{row['statement']}",
        ]
        decision = human[row["requirement_id"]]
        if decision is not None:
            lines.append(f"人工处置（不改写机器结论）：{decision['state']}；{decision['reason']}")
        for q in row["target_quotes"] + row["authority_quotes"]:
            lines.append(
                f"原文证据 {q['document_version_id']} / {q['parse_run_id']} / 物理页 {q['physical_page']}：{q['quote']}"
            )
        return lines

    result = [
        (
            "统一评审报告",
            [
                f"统一快照：{report['snapshot_id']}；评审：{report['review_id']}",
                report["basis_notice"],
                report["pipeline"]["reason"],
            ],
        ),
        ("一、废标／否决与强制性要求", [s for r in report["requirements"] for s in row_text(r)]),
        (
            "二、分类问题清单",
            [s for r in report["issues"] for s in row_text(r)]
            + [f"尚未获得本冻结整包范围的完整检测结果：{k}" for k in report["unmeasured_checks"]],
        ),
    ]
    prediction = report["prediction"]
    lines = []
    if prediction["state"] == "valid":
        score = prediction["score"]
        lines += [
            f"已校准：{score['value']} / {score['maximum']}；约80%区间：{score['low']}—{score['high']}",
            f"训练项目组：{score['training_groups']}；独立评估MAE：{score['evaluation_project_mae']}",
        ]
    for t in prediction["topics"]:
        lines.append(f"条款 {t['rule_id']}：{t['observations']}")
        if prediction["state"] == "valid":
            lines.append(f"档位观察差额（非总分归因）：{t['observed_band_gap']}")
        lines += [
            f"文档 {q['document_version_id']} / 物理页 {q['physical_page']}：{q['quote']}"
            for q in t["evidence"]
        ]
    result.append(
        (
            "三、可能的失分点" if prediction["state"] == "hidden" else "三、评分预测",
            lines + prediction["limitations"],
        )
    )
    price = report["pricing"]
    if price is not None:
        result.append(
            (
                "四、报价",
                [price["reason"]]
                if price["state"] == "unavailable"
                else [
                    f"报价模拟 {price['simulation_id']}；公式 {price['formula_id']}",
                    f"候选报价 {price['candidate_price']}；价格分 {price['price_score'] if price['price_score'] is not None else '未知'} / {price['maximum']}",
                    *price["notes"],
                ],
            )
        )
    result.append(("附录、完整响应矩阵", [s for r in report["matrix"] for s in row_text(r)]))
    return result


def document(report):
    return assemble_report(
        [
            (_clean_text(title), [_clean_text(line) for line in lines])
            for title, lines in sections(report)
        ]
    )
