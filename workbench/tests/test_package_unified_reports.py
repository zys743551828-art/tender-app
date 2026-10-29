"""Four real OOXML sections with simulated native authority; no real qualification."""

# ruff: noqa: F401,F811
from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_package_review_reports import case, human_snapshot, report, text

from packages.domain.errors import DomainError
from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_unified_reports.application import UnifiedReports
from packages.package_unified_reports.projection import compose, document, method_digest


@pytest.fixture
def packet(report):
    run = deepcopy(report)
    preview = {
        "scope": run["scope"],
        "basis": {
            k: "a" * 64
            for k in ("package_digest", "authority_digest", "inventory_digest", "identity_digest")
        },
        "documents": run["result"]["manifest"]["submitted_documents"],
    }
    preview["basis"]["authority_revision_id"] = "authority"
    projection = {
        "command_id": "cmd",
        "bid_id": run["scope"]["bid_id"],
        "scope_id": "scope",
        "input_digest": "input",
        "state": "valid",
        "topics": [],
        "limitations": ["冻结范围"],
        "score": {
            "value": "50",
            "maximum": "100",
            "low": "40",
            "high": "60",
            "training_groups": {"fit": 3},
            "evaluation_project_mae": "5",
        },
    }
    source = {"scope_manifest": {"preview": {"manifest": preview}}, "input_digest": "input"}
    pricing = {
        "formula_snapshot": {
            "bid_id": run["scope"]["bid_id"],
            "formula_version_id": "formula",
            "package_binding": {
                "package_id": run["scope"]["package_id"],
                "revision_id": run["scope"]["revision_id"],
                "authority_revision_id": "authority",
            },
            "source_authority": {
                "package_snapshot": preview["basis"]
                | {"inventory_id": run["scope"]["inventory_id"]}
            },
        },
        "current_applicability": {"applicable": True},
        "candidate_price": "120",
        "price_score": "20",
        "maximum": "30",
        "eligible": True,
        "notes": [],
    }
    snapshot = {
        "method_digest": method_digest(),
        "receipt": {"command_id": "cmd", "certificate_id": "cert", "state": "valid"},
        "packet": {"authority": {"source": {"current_source": source}}},
        "sources": {
            "run": run,
            "human": human_snapshot(run),
            "settings": {"show_prediction": True, "pricing": True},
            "pricing": pricing,
            "simulation_id": "simulation",
        },
    }
    return snapshot, projection


def test_four_parts_same_snapshot_and_word(packet):
    snapshot, prediction = packet
    report = compose(snapshot, prediction, digest(snapshot))
    content = text(document(report))
    for title in ("一、废标／否决与强制性要求", "二、分类问题清单", "三、评分预测", "四、报价"):
        assert title in content
    assert report["snapshot_id"] in content
    assert "已校准：50" in content and "候选报价 120" in content
    assert report["pipeline"]["submission_eligible"] is False


def test_hidden_and_disabled_price_do_not_leak(packet):
    snapshot, prediction = packet
    snapshot["sources"]["settings"].update(show_prediction=False, pricing=False)
    snapshot["sources"]["pricing"] = None
    prediction.update(state="hidden", score=None)
    report = compose(snapshot, prediction, digest(snapshot))
    content = text(document(report))
    assert "三、可能的失分点" in content
    assert "四、报价" not in content and "已校准：50" not in content and "MAE" not in content


@pytest.mark.parametrize(
    "attack",
    [
        "review_scope",
        "document",
        "pricing_scope",
        "pricing_authority",
        "pricing_stale",
        "prediction_input",
        "visibility",
        "human_row",
    ],
)
def test_no_cross_revision_or_partial_authority_composition(packet, attack):
    snapshot, prediction = deepcopy(packet)
    sources = snapshot["sources"]
    if attack == "review_scope":
        sources["run"]["scope"]["revision_id"] = "other"
    if attack == "document":
        sources["run"]["result"]["manifest"]["submitted_documents"][0]["file_digest"] = "f" * 64
    if attack == "pricing_scope":
        sources["pricing"]["formula_snapshot"]["package_binding"]["revision_id"] = "other"
    if attack == "pricing_authority":
        sources["pricing"]["formula_snapshot"]["source_authority"]["package_snapshot"][
            "identity_digest"
        ] = "f" * 64
    if attack == "pricing_stale":
        sources["pricing"]["current_applicability"]["applicable"] = False
    if attack == "prediction_input":
        prediction["input_digest"] = "other"
    if attack == "visibility":
        sources["settings"]["show_prediction"] = False
    if attack == "human_row":
        sources["human"]["items"][0]["row_digest"] = "f" * 64
    with pytest.raises((GovernanceError, DomainError)):
        compose(snapshot, prediction, digest(snapshot))


@pytest.mark.parametrize("change", ["hidden", "revoke", "price", "human", "cancelled_review"])
def test_final_recheck_rejects_changes_during_render(packet, change):
    initial, prediction = deepcopy(packet)

    class Tx:
        active = False

        @contextmanager
        def __call__(self):
            self.active = True
            try:
                yield self
            finally:
                self.active = False

        def read(self, *args):
            return deepcopy(initial["receipt"])

        def prepare(self, *args):
            return deepcopy(initial["packet"])

        def components(self, *args):
            return deepcopy(initial["sources"])

    tx = Tx()

    def project(p, r):
        assert not tx.active
        if change == "hidden":
            initial["sources"]["settings"]["show_prediction"] = False
        if change == "revoke":
            initial["receipt"]["state"] = "stale"
        if change == "price":
            initial["sources"]["pricing"]["candidate_price"] = "125"
        if change == "human":
            initial["sources"]["human"]["items"][0]["current"] = {"state": "rejected"}
        if change == "cancelled_review":
            initial["sources"]["run"]["operation"]["state"] = "cancelled"
        return prediction

    with pytest.raises(GovernanceError):
        UnifiedReports(tx, project).render("actor", "bid", "scope", "cmd", "review", format="docx")
    assert not tx.active


def test_repeated_request_same_snapshot_and_word_bytes(packet):
    snapshot, prediction = packet
    value = compose(snapshot, prediction, digest(snapshot))
    assert document(value) == document(
        compose(deepcopy(snapshot), deepcopy(prediction), digest(snapshot))
    )


def test_native_adapter_uses_exact_completed_run_and_native_pricing(packet, monkeypatch):
    from packages.package_unified_reports import infrastructure as native

    snapshot, _ = packet
    run = snapshot["sources"]["run"]

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Connection:
        def execute(self, query, args):
            if query.startswith(native.runs.SELECT):
                return Result({"row": True})
            return Result({"id": run["id"]})

    monkeypatch.setattr(native.runs, "view", lambda row: run)
    monkeypatch.setattr(
        native, "fetch", lambda *args: {"settings": snapshot["sources"]["settings"]}
    )
    monkeypatch.setattr(native.decisions, "current", lambda *args: snapshot["sources"]["human"])
    monkeypatch.setattr(
        native, "simulation_view", lambda *args, **kw: snapshot["sources"]["pricing"]
    )
    tx = native.NativeUnifiedTransaction(Connection())
    result = tx.components(run["scope"]["bid_id"], snapshot["packet"], run["id"], "simulation")
    assert result == snapshot["sources"]
    with pytest.raises(DomainError):
        tx.components(run["scope"]["bid_id"], snapshot["packet"], "another", "simulation")


def test_http_default_disabled_and_same_projection_for_json_word(monkeypatch, packet):
    from uuid import UUID

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from apps.api import package_unified_report_routes as routes
    from packages.package_model_live.producer import Executor
    from packages.package_prediction.application import Predictions
    from packages.package_prediction.infrastructure import NativeTransactions

    snapshot, prediction = packet
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(routes, "auth", lambda request: {"member_id": "owner"})

    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({"error": "denied"}, status_code=exc.status)

    path = f"/api/v1/bids/{UUID(int=1)}/technical-scopes/{UUID(int=2)}/formal-predictions/{UUID(int=3)}/unified-report"
    query = f"?review_id={UUID(int=4)}"
    client = TestClient(app)
    assert client.get(path + query).status_code == 503
    app.state.package_prediction_service = Predictions(
        NativeTransactions(lambda: None), Executor("/nonexistent", None)
    )

    class Service:
        def __init__(self, *args):
            pass

        def render(self, *args):
            value = compose(snapshot, prediction, digest(snapshot))
            return document(value) if args[-1] == "docx" else value

    monkeypatch.setattr(routes, "UnifiedReports", Service)
    for suffix in ("", ".docx"):
        response = client.get(path + suffix + query)
        assert (
            response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
        )
