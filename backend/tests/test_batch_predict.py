"""批量预测工具（tools/batch/predict_dataset.py）端到端：格式 A → 产品流水线 → 格式 B，缓存、续跑、失败隔离、只上传招标与正文。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from tools.batch import predict_dataset as batch

from tests.conftest import ADMIN_DSN
from tests.fakes import ScriptedLlm
from tests.pdfs import make_pdf
from tests.test_auto_pipeline import BODY, BODY_V2, TENDER, _respond

pytestmark = pytest.mark.integration

ADDENDUM = make_pdf([["补遗一 工期澄清", "总工期要求不变，仍按招标文件执行。"]])
SCORE_SHEET = make_pdf([["技术分评分汇总表", "某某公司 技术分 41.5 分"]])
NOT_A_PDF = b"this is not a pdf at all, just bytes" * 10


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sample(sample_id: str, tender: list[tuple[str, str, bytes]], body: tuple[str, bytes], **extra: Any) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "project_key": "HF-2026-001|一标段",
        "template_group": "TG-001",
        "region": "安徽省合肥市",
        "engineering_type": "市政道路",
        "scoring_scheme": "综合评估法",
        "bidder": f"{sample_id} 公司",
        "own_company": True,
        "submitted_at": "2026-04-20",
        "tender_files": [
            {"file_id": f"FILE-{i}", "path": p, "sha256": _sha(d), "pages": 1, "role": role} for i, (p, role, d) in enumerate(tender, 1)
        ],
        "body_file": {"file_id": "FILE-B", "path": body[0], "sha256": _sha(body[1]), "pages": 1, "text_layer": True},
        "label": {"target": "technical_total", "value": 41.5, "maximum": 60, "verification_status": "verified"},
        "eligible": True,
        "exclusion": None,
        **extra,
    }


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    root = tmp_path / "datasets"
    files = {
        "CASE-001_合肥/01-招标资料/招标文件.pdf": TENDER,
        "CASE-001_合肥/02-投标文件/技术标.pdf": BODY,
        "CASE-001_合肥/03-评审结果/评分汇总表.pdf": SCORE_SHEET,  # 成绩来源：绝不能上传
        "CASE-002_合肥/01-招标资料/招标文件.pdf": TENDER,
        "CASE-002_合肥/02-投标文件/技术标.pdf": BODY_V2,
        "CASE-003_合肥/01-招标资料/招标文件.pdf": TENDER,
        "CASE-003_合肥/01-招标资料/补遗一.pdf": ADDENDUM,
        "CASE-003_合肥/02-投标文件/技术标.pdf": NOT_A_PDF,
    }
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    tender1 = [("CASE-001_合肥/01-招标资料/招标文件.pdf", "tender", TENDER)]
    samples = [
        _sample("CASE-001", tender1, ("CASE-001_合肥/02-投标文件/技术标.pdf", BODY)),
        _sample(
            "CASE-002", [("CASE-002_合肥/01-招标资料/招标文件.pdf", "tender", TENDER)], ("CASE-002_合肥/02-投标文件/技术标.pdf", BODY_V2)
        ),
        _sample(
            "CASE-003",
            [("CASE-003_合肥/01-招标资料/招标文件.pdf", "tender", TENDER), ("CASE-003_合肥/01-招标资料/补遗一.pdf", "addendum", ADDENDUM)],
            ("CASE-003_合肥/02-投标文件/技术标.pdf", NOT_A_PDF),
        ),
        _sample(
            "CASE-004", tender1, ("CASE-001_合肥/02-投标文件/技术标.pdf", BODY), eligible=False, exclusion="duplicate_body", label=None
        ),
    ]
    path = tmp_path / "评分配对集.json"
    path.write_text(json.dumps({"schema": "score-pairs/1", "datasets_root": "datasets", "samples": samples}, ensure_ascii=False), "utf-8")
    return path


def _opts(dataset: Path, out: Path, cache: Path, **kw: Any) -> batch.Options:
    return batch.Options(dataset=dataset, out=out, admin_dsn=ADMIN_DSN, cache_dir=cache, poll_seconds=0.2, sample_timeout=120, **kw)


def _load(out: Path, sample_id: str) -> dict[str, Any]:
    return dict(json.loads((out / f"{sample_id}.json").read_text("utf-8")))


def _drop(db_name: str) -> None:
    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin.dispose()


def test_batch_predicts_caches_resumes_and_isolates_failures(dataset: Path, tmp_path: Path) -> None:
    llm = ScriptedLlm(_respond)
    out, cache = tmp_path / "out", tmp_path / "cache"
    summary = batch.run_batch(_opts(dataset, out, cache, keep_db=True), llm)
    assert summary.db_name is not None
    try:
        assert (summary.succeeded, summary.failed, summary.skipped, summary.excluded) == (2, 1, 0, 1)
        assert summary.bytes_left == 0  # 每个样本完成即回收内存对象
        assert not (out / "CASE-004.json").exists()

        # 只上传了招标文件、补遗与正文；成绩来源文件从未入库
        url = make_url(ADMIN_DSN).set(database=summary.db_name).render_as_string(hide_password=False)
        eng = create_engine(url)
        with eng.connect() as conn:
            uploaded = {r[0] for r in conn.execute(text("SELECT a.sha256 FROM file_versions fv JOIN artifacts a ON a.id=fv.artifact_id"))}
            roles = {r[0] for r in conn.execute(text("SELECT DISTINCT role FROM files"))}
            deadlines = {r[0] for r in conn.execute(text("SELECT deadline FROM projects"))}
        eng.dispose()
        assert uploaded == {_sha(d) for d in (TENDER, BODY, BODY_V2, ADDENDUM, NOT_A_PDF)} and _sha(SCORE_SHEET) not in uploaded
        assert roles == {"tender", "supplement", "body"} and deadlines == {None}
    finally:
        _drop(summary.db_name)

    one = _load(out, "CASE-001")
    assert one["schema"] == "system-prediction/1" and one["status"] == "succeeded" and one["error"] is None
    assert one["model"] == "scripted-test" and one["prompt_version"] and len(one["fingerprint"]) == 64 and len(one["code_sha256"]) == 64
    assert one["inputs"] == {"tender_sha256": [_sha(TENDER)], "body_sha256": _sha(BODY)}
    assert one["technical_full_score"] == "60"
    assert one["prediction"] == {"status": "candidate", "estimate": "4", "low": "2", "high": "6", "maximum": "8"}
    (item,) = one["items"]
    assert {*batch.ITEM_KEYS, "rule_id", "evidence_ids", "assessment", "limitations"} <= set(item)
    assert item["max_points"] == "8" and item["estimate"] == "4" and item["evidence_count"] == 1
    assert item["rule_basis"] == "unconfirmed" and item["failed"] is False
    assert one["artifact_extra"]["prompt_version"] == one["prompt_version"] and one["artifact_extra"]["coverage"]["status"] == "complete"
    assert "items" not in one["artifact_extra"] and "usage" not in one["artifact_extra"]
    assert one["rules"] == {"disqualification": 1, "mandatory": 1, "scoring": 1, "with_points": 1, "total": 3}
    compliance = {k: one["compliance"][k] for k in ("qualification_total", "satisfied", "violated", "unclear", "failed", "coverage")}
    assert compliance == {"qualification_total": 2, "satisfied": 1, "violated": 1, "unclear": 0, "failed": 0, "coverage": "complete"}
    assert one["findings"]["disqualification"] == 1 and set(one["findings"]) == {
        "disqualification",
        "response",
        "consistency",
        "scope",
        "improvement",
    }
    assert one["body"]["pages"] == 4 and one["body"]["chars"] > 50
    assert one["usage"]["calls"] > 0 and one["usage"]["prompt_tokens"] == 10 * one["usage"]["calls"]

    two = _load(out, "CASE-002")
    assert two["status"] == "succeeded" and two["compliance"]["violated"] == 0

    three = _load(out, "CASE-003")  # 正文不是 PDF：解析失败，如实记录，不影响其他样本
    assert three["status"] == "failed" and "parse" in three["error"] and three["prediction"] is None
    assert three["inputs"]["tender_sha256"] == [_sha(TENDER), _sha(ADDENDUM)] and three["usage"]["calls"] == 0

    calls = len(llm.calls)
    first = {sid: _load(out, sid) for sid in ("CASE-001", "CASE-002")}

    # 续跑：指纹一致的成功结果跳过；--skip-failed 时失败的也跳过；不建库、不调用模型
    again = batch.run_batch(_opts(dataset, out, cache, skip_failed=True), llm)
    assert (again.succeeded, again.failed, again.skipped) == (0, 0, 3) and again.db_name is None and len(llm.calls) == calls

    # 换输出目录、沿用缓存：全部调用命中缓存，结果与首次一致
    out2 = tmp_path / "out2"
    replay = batch.run_batch(_opts(dataset, out2, cache, only=["CASE-001", "CASE-002"], concurrency=1), llm)
    assert (replay.succeeded, replay.failed) == (2, 0) and len(llm.calls) == calls
    assert replay.stats.calls == 0 and replay.stats.cache_hits > 0
    for sid, before in first.items():
        after = _load(out2, sid)
        assert after["usage"]["calls"] == 0 and after["usage"]["cache_hits"] == before["usage"]["calls"] + before["usage"]["cache_hits"]
        for key in ("prediction", "technical_full_score", "rules", "compliance", "findings", "body", "fingerprint"):
            assert after[key] == before[key], key
        assert [{k: i[k] for k in batch.ITEM_KEYS} for i in after["items"]] == [{k: i[k] for k in batch.ITEM_KEYS} for i in before["items"]]

    # 新缓存、逐份运行：两份样本招标文件相同，规则提取只付一次费，后一份命中缓存
    out3 = tmp_path / "out3"
    serial = batch.run_batch(_opts(dataset, out3, tmp_path / "cache2", only=["CASE-001", "CASE-002"], concurrency=1), llm)
    assert serial.succeeded == 2 and serial.stats.cache_hits == 1
    assert [_load(out3, sid)["usage"]["cache_hits"] for sid in ("CASE-001", "CASE-002")] == [0, 1]


def test_estimate_only_does_not_call_the_model(dataset: Path, tmp_path: Path) -> None:
    llm = ScriptedLlm(_respond)
    summary = batch.run_batch(_opts(dataset, tmp_path / "out", tmp_path / "cache", estimate_only=True, price_in=2.0, price_out=8.0), llm)
    est = summary.estimate
    assert est is not None and not llm.calls and summary.db_name is None
    assert est["samples"] == 3 and est["unique_tender_sets"] == 2  # CASE-001 与 CASE-002 招标文件相同：规则提取只计一次
    assert est["calls"]["rules"] >= 2 and est["calls"]["diagnosis"] >= 2 and est["calls"]["prediction"] >= 1
    assert est["prompt_tokens"] > 0 and est["completion_tokens"] > 0 and est["cost"] > 0
    assert any("调用次数" in line for line in summary.lines())


def test_cached_llm_replays_with_this_run_identifiers(tmp_path: Path) -> None:
    """同一内容、不同随机标识的调用命中同一缓存条目，回复里的标识换回本次的。"""
    seen: list[str] = []

    def respond(system: str, user: str) -> Any:
        seen.append(user)
        return {"evidence_ids": [user.split('"')[1]]}

    cached = batch.CachedLlm(ScriptedLlm(respond), tmp_path)
    first = cached.complete(system="s", user='<doc id="evd_0123456789abcdef">原文</doc>')
    second = cached.complete(system="s", user='<doc id="evd_fedcba9876543210">原文</doc>')
    assert json.loads(first.text) == {"evidence_ids": ["evd_0123456789abcdef"]}
    assert json.loads(second.text) == {"evidence_ids": ["evd_fedcba9876543210"]} and second.usage.calls == 0
    assert len(seen) == 1 and cached.total.calls == 1 and cached.total.cache_hits == 1
    cached.complete(system="s", user='<doc id="evd_fedcba9876543210">别的原文</doc>', max_tokens=100)
    assert len(seen) == 2
