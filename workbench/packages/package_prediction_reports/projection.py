"""Verified existing /3 citations and deterministic existing Word serialization."""

from collections import Counter
from decimal import Decimal
from pathlib import Path

from packages.domain import package_review_reports as existing_report
from packages.domain.package_report_docx import WRITER_DIGEST, assemble_report
from packages.domain.review_identity import digest
from packages.model_governance import package_complete_handoff as handoff
from packages.package_model_live import producer
from packages.package_model_registry import artifact
from packages.storage.private_cas import PrivateContentStore, sha

VERSION = "package-formal-prediction-report/1"


def method_digest():
    return digest(
        {
            "version": VERSION,
            "sources": {
                p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))
            },
            "producer": producer.method_digest(),
            "writer": WRITER_DIGEST,
            "report_text_policy": existing_report.source_profile(),
        }
    )


class MaterialProjection:
    def __init__(self, store, index):
        self.store, self.index = store, index

    def __call__(self, packet, receipt):
        src = packet["authority"]["source"]
        compute = {
            "source": src["current_source"],
            "artifact": src["model"],
            "reference": packet["reference"],
        }
        with PrivateContentStore(self.store) as store:
            computed = producer.consume(compute, store, self.index)
            loaded = handoff.load(store, self.index, **packet["reference"])
        if (
            computed["mode"] != "live"
            or computed["input_digest"] != receipt["input_digest"]
            or computed["model_id"] != receipt["model_id"]
            or (
                receipt["state"] == "valid"
                and Decimal(computed["value"]) != Decimal(receipt["value"])
            )
        ):
            artifact.fail()
        visible = receipt["state"] == "valid"
        rules = {
            r["rule_id"]: r
            for r in loaded.bundle.context.metadata["rules"]
            if r["selection"] == "include"
        }
        originals = {d["document_version_id"]: d["digest"] for d in compute["source"]["originals"]}
        topics = []
        citation_bytes = 0
        for rule_id, rule in rules.items():
            rows = [a for a in loaded.attempts if a.rule_id == rule_id]
            if (
                len(rows) != 3
                or {a.slot for a in rows} != {1, 2, 3}
                or any(a.generation is None for a in rows)
            ):
                artifact.fail()
            points = {b["band_id"]: Decimal(str(b["source"]["points"])) for b in rule["bands"]}
            maximum = Decimal(str(rule["frozen_rule"]["rule_snapshot"]["max_points"]))
            loss = (
                maximum - sum((points[a.generation.data["band_id"]] for a in rows), Decimal(0)) / 3
            )
            evidence = {}
            for row in rows:
                for citation in row.generation.data["evidence"]:
                    citation_bytes += len(citation["quote"].encode("utf-8"))
                    if citation_bytes > 8 * 1024 * 1024:
                        artifact.fail()
                    evidence[digest(citation)] = citation | {
                        "file_digest": originals[citation["document_version_id"]]
                    }
            # Original citations were rechecked against native page/image and exact quote
            # by producer.consume/handoff; never invent a citation for an unsupported claim.
            dimensions = {
                k: dict(Counter(a.generation.data["dimensions"][k] for a in rows))
                for k in ("specificity", "validity", "consistency")
            }
            topics.append(
                (
                    loss,
                    {
                        "rule_id": rule_id,
                        "evidence": [evidence[k] for k in sorted(evidence)],
                        "observations": {
                            k: ("supported" if d.get("supported") == 3 else "needs_review")
                            for k, d in dimensions.items()
                        },
                        "rule_maximum": format(maximum, "f") if visible else None,
                        "observed_band_gap": format(loss, "f") if visible else None,
                    },
                )
            )
        topics.sort(key=lambda pair: (-pair[0], pair[1]["rule_id"]))
        fields = (
            "value",
            "maximum",
            "low",
            "high",
            "interval_level",
            "training_groups",
            "evaluation_project_mae",
        )
        return {
            "schema": VERSION,
            "report_method_digest": method_digest(),
            "command_id": receipt["command_id"],
            "bid_id": receipt["bid_id"],
            "scope_id": receipt["scope_id"],
            "certificate_id": receipt["certificate_id"],
            "model_id": receipt["model_id"],
            "input_digest": receipt["input_digest"],
            "state": receipt["state"],
            "score": {k: receipt[k] for k in fields} if visible else None,
            "topics": [t for _, t in topics[:10]],
            "limitations": [
                "条款档位观察差额不是校准模型总分的分解；维度未获一致支持不等于已经证明缺失。",
                "仅描述本次复验时的资格与冻结输入；不证明真实预测准确性或交易平台提交。",
            ],
            "provider_requests": 0,
        }


def document(report):
    visible = report["state"] == "valid"
    sections = [
        (
            "正式预测核对报告" if visible else "可能的失分点",
            [
                f"预测记录：{report['command_id']}；认证：{report['certificate_id']}；输入：{report['input_digest']}",
                *report["limitations"],
            ],
        )
    ]
    if visible:
        score = report["score"]
        sections.append(
            (
                "已校准估计（限认证绑定输入）",
                [
                    f"估计：{score['value']} / {score['maximum']}；约 80% 区间：{score['low']}—{score['high']}",
                    f"拟合/开发/校准项目组：{score['training_groups']['fit']} / {score['training_groups']['development']} / {score['training_groups']['calibration']}；独立评估项目 MAE：{score['evaluation_project_mae']}",
                ],
            )
        )
    for topic in report["topics"]:
        names = {"specificity": "具体性", "validity": "有效性", "consistency": "一致性"}
        lines = [
            "维度核对："
            + "；".join(
                names[k] + ("：三次一致支持" if v == "supported" else "：需要复核")
                for k, v in topic["observations"].items()
            )
        ]
        if visible:
            lines.append(
                f"条款满分：{topic['rule_maximum']}；档位观察差额：{topic['observed_band_gap']}（非模型归因）"
            )
        lines += [
            f"原文证据：文档 {e['document_version_id']}；解析 {e['parse_run_id']}；物理页 {e['physical_page']}；页图 {e['page_image_digest']}；引文：{e['quote']}"
            for e in topic["evidence"]
        ]
        sections.append((f"可能失分点 · 条款 {topic['rule_id']}", lines))
    return assemble_report(
        [
            (
                existing_report._clean_text(title),
                [existing_report._clean_text(line) for line in lines],
            )
            for title, lines in sections
        ]
    )
