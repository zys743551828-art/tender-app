"""研究产出的登记（bidwb-admin）：契约与放行门槛、追溯链、路由切换与撤下、锚点包（真实 PG、内存对象存储）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bidwb import admin, db
from bidwb.ai import anchors
from bidwb.runtime import Container
from bidwb.services import model_registry
from tests.fakes import scoring_bundle

pytestmark = pytest.mark.integration


def _write(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def cli(settings, engine, store, make_member):  # type: ignore[no-untyped-def]
    make_member("lead")

    def run(*argv: str) -> int:
        return admin.main(list(argv), container=lambda: Container(settings, engine, store))

    return run


def test_register_route_replace_and_unroute(cli, engine, store, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    report = _write(tmp_path / "report.json", {"protocol": "评测协议", "folds": 5})
    first = _write(tmp_path / "m1.json", scoring_bundle())
    args = ["--report", report, "--reviewer", "lead", "--environment", "business"]
    assert cli("register-scoring-model", first, *args) == 0
    with engine.connect() as conn:
        route = model_registry.routed(conn, "technical_total", "business")
        assert route is not None and route["revision"] == 1 and route["components_json"]["model_id"] == scoring_bundle()["model_id"]
        chain = db.one(
            conn,
            """SELECT v.purpose, v.status, v.scope, d.purpose AS dataset_purpose, d.member_count, d.grouping, e.status AS experiment_status,
                      e.strategy, ra.contract_version AS report_contract, ba.contract_version AS bundle_contract
               FROM releases r JOIN validations v ON v.id=r.validation_id JOIN model_bundles b ON b.id=r.bundle_id
               JOIN experiments e ON e.id=b.experiment_id JOIN dataset_snapshots d ON d.id=e.dataset_id
               JOIN artifacts ra ON ra.id=v.report_artifact_id JOIN artifacts ba ON ba.id=b.artifact_id WHERE r.id=:r""",
            {"r": route["release_id"]},
        )
        assert chain is not None
        assert dict(chain) == {
            "purpose": "technical_total_business",
            "status": "passed",
            "scope": "工程类型：市政道路；地区：合肥",
            "dataset_purpose": "technical_total_business",
            "member_count": 280,
            "grouping": "project|template|body",
            "experiment_status": "succeeded",
            "strategy": "ridge+isotonic",
            "report_contract": "scoring-model-report",
            "bundle_contract": "scoring-model/1",
        }
        assert json.loads(store.get(route["artifact_key"])) == scoring_bundle()  # 原件原样保存
    assert cli("register-scoring-model", first, *args) == 0  # 同一模型再登记：不改动
    assert "未做改动" in capsys.readouterr().out
    second = _write(tmp_path / "m2.json", scoring_bundle(intercept=71.0))
    assert cli("register-scoring-model", second, *args) == 0
    with engine.connect() as conn:
        replaced = model_registry.routed(conn, "technical_total", "business")
        assert replaced is not None and replaced["revision"] == 2
        previous = db.scalar(conn, "SELECT previous_release_id FROM releases WHERE id=:r", {"r": replaced["release_id"]})
        assert previous == route["release_id"]
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='technical_total.release'") == 2
    assert cli("list-scoring-models") == 0
    assert "business" in capsys.readouterr().out
    assert cli("unroute-scoring-model", "--environment", "business", "--reviewer", "lead") == 0
    with engine.connect() as conn:
        assert model_registry.routed(conn, "technical_total", "business") is None
    assert cli("unroute-scoring-model", "--environment", "business") == 1  # 没有路由可撤


def test_contract_and_business_gate(cli, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    report = _write(tmp_path / "report.json", {})
    failed = _write(tmp_path / "failed.json", scoring_bundle(evaluation={"n": 40, "mae_pct": 6.0, "verdict": "failed"}))
    assert cli("register-scoring-model", failed, "--report", report, "--reviewer", "lead", "--environment", "business") == 1
    assert "passed" in capsys.readouterr().err
    assert cli("register-scoring-model", failed, "--report", report, "--reviewer", "lead", "--environment", "shadow") == 0
    tampered = _write(tmp_path / "tampered.json", {**scoring_bundle(), "intercept": 0.0})
    assert cli("register-scoring-model", tampered, "--report", report, "--reviewer", "lead", "--environment", "shadow") == 1
    assert "model_id" in capsys.readouterr().err
    good = _write(tmp_path / "good.json", scoring_bundle())
    assert cli("register-scoring-model", good, "--report", report, "--reviewer", "nobody", "--environment", "shadow") == 1


def test_register_anchor_pack(cli, engine, store, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    raw: dict[str, Any] = {
        "schema": "anchor-pack/1",
        "created_at": "2026-10-01T00:00:00+00:00",
        "anchors": [
            {
                "anchor_id": f"A{n}",
                "group_id": f"G{n}",
                "body_sha256": f"{n:064x}",
                "technical_pct": 60.0 + n,
                "sections": [{"id": "S1", "title": "第一章", "text": "内容"}],
            }
            for n in (1, 2)
        ],
    }
    raw["pack_id"] = anchors.pack_id_of(raw)
    pack = _write(tmp_path / "pack.json", raw)
    assert cli("register-anchor-pack", pack, "--reviewer", "lead", "--environment", "business") == 0
    with engine.connect() as conn:
        route = model_registry.routed(conn, "anchor_pack", "business")
        assert route is not None and route["components_json"]["anchors"] == 2 and "sections" not in route["components_json"]
        from bidwb.services.anchor_packs import routed_pack

        loaded = routed_pack(conn, store, "prj_any")
        assert loaded is not None and loaded.pack_id == raw["pack_id"] and loaded.environment == "business"
    single = {**raw, "anchors": raw["anchors"][:1]}
    single["pack_id"] = anchors.pack_id_of({k: v for k, v in single.items() if k != "pack_id"})
    assert cli("register-anchor-pack", _write(tmp_path / "one.json", single), "--reviewer", "lead", "--environment", "shadow") == 1
    assert cli("unroute-anchor-pack", "--environment", "business") == 0
    assert cli("list-anchor-packs") == 0
