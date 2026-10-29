"""Real CAS and OOXML serialization with simulated authority, never real qualification."""

# ruff: noqa: F811
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pytest
from test_package_business_shadow import mirror  # noqa: F401
from test_package_feature_training_io import cohort  # noqa: F401
from test_package_model_observation import material  # noqa: F401
from test_package_prediction import setup

from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_model_live import producer
from packages.package_prediction_reports import projection
from packages.package_prediction_reports.application import Reports


@pytest.fixture(scope="module")
def source(mirror):
    root, index, material = mirror
    packet, cert = setup()
    src = deepcopy(material["source"])
    src["mode"] = "live"
    authority = packet["authority"]
    source = authority["source"]
    source["current_source"] = src
    for event in ("shadow", "rollback"):
        source[event]["source"] = deepcopy(src)
        source[event]["result"]["source_digest"] = digest(src)
        source[event]["result"]["input_digest"] = src["input_digest"]
    authority["certificate"]["source_digest"] = digest(source)
    packet["reference"] = material["reference"]
    calculated = producer.Executor(root, index)(
        {"source": src, "artifact": source["model"], "reference": material["reference"]}
    )
    value = Decimal(calculated["value"])
    candidate = source["model"]["source"]["candidate"]
    radius = Decimal(candidate["intervals"]["0.8"]["radius"])
    receipt = {
        "state": "valid",
        "command_id": "command",
        "bid_id": src["bid_id"],
        "scope_id": src["scope_id"],
        "certificate_id": cert,
        "model_id": source["model"]["model_id"],
        "input_digest": src["input_digest"],
        "value": calculated["value"],
        "maximum": "100",
        "low": str(max(Decimal(0), value - radius)),
        "high": str(min(Decimal(100), value + radius)),
        "interval_level": "0.8",
        "training_groups": candidate["groups"],
        "evaluation_project_mae": "5",
    }
    return root, index, packet, receipt


class Transactions:
    def __init__(self, packet, receipt):
        self.packet, self.receipt = deepcopy(packet), deepcopy(receipt)
        self.active = False

    @contextmanager
    def __call__(self):
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    def read(self, *args):
        if args[0] != "owner":
            raise GovernanceError("DENIED", "cross member")
        return deepcopy(self.receipt)

    def prepare(self, *args):
        return deepcopy(self.packet)


def test_actual_citations_and_word_visible_and_hidden(source):
    root, index, packet, receipt = deepcopy(source)
    project = projection.MaterialProjection(root, index)
    visible = project(packet, receipt)
    assert visible["topics"]
    with ZipFile(BytesIO(projection.document(visible))) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "约 80% 区间" in xml and "独立评估项目 MAE" in xml
    for t in visible["topics"]:
        assert all(
            e["quote"] and e["physical_page"] > 0 and len(e["file_digest"]) == 64
            for e in t["evidence"]
        )
    receipt["state"] = "hidden"
    receipt["value"] = None
    hidden = project(packet, receipt)
    assert hidden["score"] is None
    assert all(
        t["observed_band_gap"] is None and t["rule_maximum"] is None for t in hidden["topics"]
    )
    with ZipFile(BytesIO(projection.document(hidden))) as archive:
        xml = archive.read("word/document.xml").decode()
    for forbidden in ("估计：", "区间：", "MAE：", "条款满分：", "档位观察差额："):
        assert forbidden not in xml
    assert "原文证据" in xml and "可能的失分点" in xml


@pytest.mark.parametrize(
    "attack",
    ["before_stale", "after_stale", "after_hidden", "input_change", "cross_member", "cpu_mutation"],
)
def test_recheck_before_and_after_bytes_without_sql_during_render(source, attack):
    root, index, packet, receipt = source
    tx = Transactions(packet, receipt)
    if attack == "before_stale":
        tx.receipt["state"] = "stale"

    def project(p, r):
        assert not tx.active
        result = projection.MaterialProjection(root, index)(p, r)
        if attack == "after_stale":
            tx.receipt["state"] = "stale"
        elif attack == "after_hidden":
            tx.receipt["state"] = "hidden"
        elif attack == "input_change":
            tx.packet["reference"]["command_id"] = "changed"
        elif attack == "cpu_mutation":
            p["reference"]["command_id"] = "changed"
        return result

    with pytest.raises(GovernanceError):
        Reports(tx, project).render(
            "other" if attack == "cross_member" else "owner",
            receipt["bid_id"],
            receipt["scope_id"],
            receipt["command_id"],
            "docx",
        )
    assert not tx.active


def test_mismatched_prediction_cannot_borrow_material_citations(source):
    root, index, packet, receipt = deepcopy(source)
    receipt["input_digest"] = "f" * 64
    with pytest.raises(GovernanceError):
        projection.MaterialProjection(root, index)(packet, receipt)


def test_no_new_report_store_or_legacy_method_mutation():
    from pathlib import Path

    source = Path("packages/package_prediction_reports/application.py").read_text()
    assert "INSERT" not in source and "self.snapshot" in source
    assert (
        "assemble_report" in Path("packages/package_prediction_reports/projection.py").read_text()
    )


def test_http_report_and_word_share_configured_consumer_and_no_store(source, monkeypatch):
    from uuid import UUID

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from apps.api import package_prediction_report_routes as routes
    from packages.domain.errors import DomainError
    from packages.package_prediction.application import Predictions

    root, index, packet, receipt = source
    tx = Transactions(packet, receipt)
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(routes, "auth", lambda request: {"member_id": "owner"})

    @app.exception_handler(DomainError)
    async def errors(request, exc):
        return JSONResponse({"error": "denied"}, status_code=exc.status)

    path = f"/api/v1/bids/{UUID(int=1)}/technical-scopes/{UUID(int=2)}/formal-predictions/{UUID(int=3)}"
    client = TestClient(app)
    assert client.get(path + "/report").status_code == 503
    app.state.package_prediction_service = Predictions(tx, producer.Executor(root, index))
    for suffix in ("/report", "/report.docx"):
        response = client.get(path + suffix)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
    tx.receipt["state"] = "stale"
    assert client.get(path + "/report.docx").status_code == 409
