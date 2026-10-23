"""Actual optional denominator registry + full identity-v2 package joins.

Fresh isolated extension installation only, actual nonowner API registration,
synthetic originals and declaration. No retrospective research SQL is installed.
"""
# ruff: noqa: F401,F811

import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from test_package_technical_eligibility_pg import api as eligibility_api
from test_package_technical_eligibility_pg import frozen
from test_package_technical_scope_pg import (
    database as scope_database,
)
from test_package_technical_scope_pg import (
    exact,
    headers,
    inventory,
    uid,
)
from test_package_technical_scope_pg import (
    requirements as scope_requirements,
)
from test_package_technical_scope_pg import (
    world as scope_world,
)
from test_stable_lot_identity import post

from apps.api.technical_scale_routes import router as scale_router
from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.runtime import connection, sha
from packages.identity.repository import record_binding
from packages.model_governance.scale_contracts import extend_openapi as scale_openapi
from packages.rag.indexing import original_source_id

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = "技术总分满分为60分，量尺为未加权原始分。"
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_TECHNICAL_SCOPE_PG") != "1",
    reason="fresh isolated optional F06 authority PG required",
)


@pytest.fixture(scope="module")
def database():
    source = scope_database.__wrapped__()
    value = next(source)
    try:
        for name in (
            "deploy/sql/model-governance.sql",
            "deploy/sql/historical-backtest.sql",
            "deploy/sql/technical-scale-authority.sql",
            "deploy/sql/technical-scale-package-identity.sql",
        ):
            value["owner"].execute((ROOT / name).read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture
def api(database):
    source = eligibility_api.__wrapped__(database)
    value = next(source)
    app = value["app"]
    if not any(
        getattr(route, "path", "") == "/api/v1/technical-scale-capabilities"
        for route in app.router.routes
    ):
        app.include_router(scale_router)
    app.openapi_schema = None
    try:
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture
def world(api):
    w = scope_world.__wrapped__(api)
    with w["database"]["owner"].transaction():
        c = w["database"]["owner"]
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,99,'text',%s,%s)",
            (
                uid(),
                w["scope"].bid_id,
                w["member"].parse.parse_run_id,
                DECLARATION,
                sha(DECLARATION.encode()),
            ),
        )
        w["member"] = replace(
            w["member"],
            parse=read_parse_identity(
                c,
                w["scope"].bid_id,
                w["member"].document_version_id,
                w["member"].parse.parse_run_id,
            ),
        )
    return w


@pytest.fixture
def requirements(world):
    w = scope_requirements.__wrapped__(world)
    with connection() as c:
        material = c.execute(
            "SELECT material_id FROM design.rule_sets WHERE bid_id=%s AND id=%s",
            (w["scope"].bid_id, w["inventory_body"]["rule_set_id"]),
        ).fetchone()["material_id"]
        authority = c.execute(
            "SELECT document_version_id FROM design.bid_package_members WHERE revision_id=%s",
            (w["inventory_body"]["authority_revision_id"],),
        ).fetchone()["document_version_id"]
        c.execute(
            "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'tender',0)",
            (material, w["scope"].bid_id, authority),
        )
        c.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s WHERE bid_id=%s",
            (material, w["scope"].bid_id),
        )
    return w


def register_scale(w):
    bid = w["scope"].bid_id
    context = w["client"].get(f"/api/v1/bids/{bid}/technical-scale-context")
    assert context.status_code == 200, context.text
    ctx = context.json()
    assert ctx["identity"]["binding_status"] == "confirmed"
    assert ctx["identity"]["identity_version"] == "bid-identity/2"
    doc = ctx["documents"][0]
    block = next(row for row in doc["evidence"] if row["text_content"] == DECLARATION)
    body = {
        "intent": "confirm",
        "context": {"purpose": "current_prebid"},
        "technical_maximum": "60.00",
        "scale_description": "未加权原始分",
        "aggregation": {
            "status": "unknown",
            "description": "No executable official aggregation supplied",
        },
        "evidence_refs": [
            {
                "document_version_id": doc["document_version_id"],
                "blob_digest": doc["blob_digest"],
                "parse_id": doc["parse_id"],
                "physical_page": block["physical_page"],
                "evidence_id": block["id"],
                "quote": block["text_content"],
                "supported_fields": ["technical_maximum", "scale_description"],
            }
        ],
        "reason": "Synthetic full identity-v2 exact authority declaration; no score qualification",
    }
    result = w["client"].post(
        f"/api/v1/bids/{bid}/technical-scales",
        json=body,
        headers=headers(w, etag=context.headers["etag"]),
    )
    assert result.status_code == 201, result.text
    actual = scale_openapi(w["app"].openapi())
    Draft202012Validator(
        {"$ref": "#/components/schemas/TechnicalScaleView", "components": actual["components"]}
    ).validate(result.json())
    return result


def test_native_sourced_maximum_matches_scope_but_aggregation_and_prediction_stay_unavailable(
    exact,
):
    w = exact
    saved, path = frozen(w)
    registered = register_scale(w)
    scale = registered.json()
    assert scale["maximum_usable"] and scale["technical_maximum"] == "60.00"
    before = list(w["io"]["reads"])
    result = w["client"].get(path + "/scoring-context", params={"scale_id": scale["id"]})
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["current_input"]["state"] == "matched"
    assert value["denominator"]["state"] == "matched"
    assert value["denominator"]["technical_maximum"] == "60.00"
    assert value["denominator"]["maximum_usable"] and not value["denominator"]["aggregation_usable"]
    assert value["numeric_prediction"] is None and not value["formal_scoring_eligible"]
    assert w["io"]["reads"] == before
    assert w["client"].get(path).json() == saved
    destination = os.environ.get("FUSION_TECHNICAL_SCALE_FIXTURE")
    if destination:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema": "package-technical-scale-http-fixture/1",
                    "evidence": "Actual optional authority PG and nonowner ASGI; synthetic complete declaration, no scoring provider",
                    "basePath": path,
                    "scope": saved,
                    "scale": scale,
                    "scoringContext": value,
                    "scoringEtag": result.headers["etag"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(scale["evidence_refs"][0]["document_version_id"])),),
        )
    changed = w["client"].get(path + "/scoring-context", params={"scale_id": scale["id"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["denominator"]["technical_maximum"] is None
    assert not changed.json()["denominator"]["maximum_usable"]


@pytest.mark.parametrize("change", ["bidder", "lot", "round"])
def test_native_confirmed_identity_change_never_reuses_old_maximum(exact, change):
    w = exact
    saved, path = frozen(w)
    scale = register_scale(w).json()
    if change == "bidder":
        bidder = post(
            w,
            "/identity/bidders",
            {"name": "new actual bidder", "reason": "synthetic identity correction"},
        ).json()["bidder"]
        with connection() as c:
            c.execute(
                "UPDATE design.bid_profiles SET bidder_id=%s WHERE bid_id=%s",
                (bidder["id"], w["scope"].bid_id),
            )
    else:
        lot = w["scope"].lot_id
        if change == "lot":
            lot = post(
                w,
                "/identity/lots",
                {
                    "engineering_project_id": w["scope"].engineering_project_id,
                    "label": "same visible lot",
                    "reason": "new distinct stable lot",
                },
            ).json()["id"]
        round_value = post(
            w,
            "/identity/rounds",
            {
                "engineering_project_id": w["scope"].engineering_project_id,
                "lot_id": lot,
                "round_no": 1 if change == "lot" else 2,
                "reason": "synthetic exact round correction",
            },
        ).json()
        with connection() as c:
            c.execute(
                "UPDATE design.bid_profiles SET round_id=%s WHERE bid_id=%s",
                (round_value["id"], w["scope"].bid_id),
            )
    with connection() as c:
        record_binding(
            c,
            UUID(w["scope"].bid_id),
            UUID(w["actor"]),
            None,
            reason="Synthetic new confirmed full identity",
            confirmed=True,
        )
    result = w["client"].get(path + "/scoring-context", params={"scale_id": scale["id"]})
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["current_input"]["state"] == "changed"
    assert value["denominator"]["technical_maximum"] is None
    assert not value["denominator"]["maximum_usable"]
    old = w["client"].get(f"/api/v1/technical-scales/{scale['id']}")
    assert old.status_code == 200 and old.json()["state"] == "needs_revalidation"
    assert old.json()["identity"] == scale["identity"]
    assert w["client"].get(path).json() == saved


def test_historical_branch_is_unchanged_and_adapter_has_no_worker_grants():
    original = (ROOT / "deploy/sql/technical-scale-authority.sql").read_text()
    adapter = (ROOT / "deploy/sql/technical-scale-package-identity.sql").read_text()
    original_branch = original.split(" IF v.purpose='historical_backtest' THEN", 1)[1].split(
        " END IF;", 1
    )[0]
    adapter_branch = adapter.split(" IF v.purpose='historical_backtest' THEN", 1)[1].split(
        " END IF;", 1
    )[0]

    def statements(value):
        return " ".join(
            line.strip() for line in value.splitlines() if not line.strip().startswith("--")
        )

    assert statements(original_branch) == statements(adapter_branch)
    assert "GRANT " not in adapter and "UPDATE " not in adapter and "INSERT " not in adapter
