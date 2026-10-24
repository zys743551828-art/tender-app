"""Native scope, exact parses, complete HTTP bytes and synthetic page projection."""
# ruff: noqa: F401,F811

import asyncio
import io
import json
import os
import secrets
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from reportlab.pdfgen import canvas
from test_bid_package_requirements_api import inventory as append_inventory
from test_package_current_original_pg import ADMIN_DSN, api, requirements, saved
from test_package_current_original_pg import database as original_database
from test_package_current_original_set_pg import wire
from test_package_technical_scope_pg import exact as base_exact
from test_package_technical_scope_pg import world as base_world

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as material
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_current_scope as scope
from packages.model_governance import package_current_sources as sources
from packages.model_governance import package_technical_assets as assets

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_CURRENT_MATERIAL_PG") != "1",
    reason="explicit grouped current material required",
)
LOGIN = "fusion_current_parse_material_verify"


@pytest.fixture(scope="module")
def database():
    base = original_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    password = secrets.token_urlsafe(36)
    try:
        assert not owner.execute(
            "SELECT FROM pg_roles WHERE rolname=ANY(%s)", ([LOGIN, sources.GROUP],)
        ).fetchone()
        owner.execute(
            (Path(__file__).parents[1] / "deploy/sql/package-current-source-grants.sql").read_text(
                encoding="utf-8"
            )
        )
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(LOGIN), sql.Literal(password))
        )
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(sources.GROUP), sql.Identifier(LOGIN))
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=LOGIN, password=password)
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as verifier:
            yield value | {"parse_verifier": verifier}
    finally:
        try:
            next(base)
        except StopIteration:
            pass
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(LOGIN)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(sources.GROUP)))


@pytest.fixture(scope="module")
def pdf_data():
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(400, 500), invariant=1)
    for page in (1, 2):
        pdf.drawString(10, 80, f"Synthetic native material {page}")
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


@pytest.fixture
def world(api, pdf_data, monkeypatch):
    import test_package_technical_scope_pg as fixtures

    monkeypatch.setattr(fixtures, "RAW", pdf_data)
    return base_world.__wrapped__(api)


@pytest.fixture
def exact(requirements, monkeypatch):
    w = base_exact.__wrapped__(requirements, monkeypatch)
    owner = w["database"]["owner"]
    authority = w["inventory"]["manifest"]["authority_revision_id"]
    evidence = [
        row["id"]
        for row in owner.execute(
            "SELECT e.id::text FROM design.evidence_blocks e JOIN design.bid_package_members m ON m.parse_run_id=e.parse_id WHERE m.revision_id=%s ORDER BY e.physical_page,e.ordinal",
            (authority,),
        ).fetchall()
    ]
    assert len(evidence) == 3
    rule = str(uuid4())
    owner.execute(
        "INSERT INTO design.rule_items(id,bid_id,rule_set_id,kind,statement,conditions,exceptions,max_points,evidence_ids,bands) VALUES(%s,%s,%s,'scoring','Synthetic multi-source rule',%s,%s,10,%s,%s)",
        (
            rule,
            w["scope"].bid_id,
            w["inventory_body"]["rule_set_id"],
            Jsonb(["condition A", "condition B"]),
            Jsonb(["exception A", "exception B"]),
            evidence,
            Jsonb(
                [
                    {"label": "complete", "description": "all required material", "points": "10"},
                    {"label": "partial", "description": "partial material", "points": "5"},
                ]
            ),
        ),
    )
    w["inventory_body"]["mappings"].append(
        {
            "rule_id": rule,
            "categories": ["technical"],
            "target_part_ids": ["tech", "appendix/table"],
            "minimum_count": None,
            "applicability": "applicable",
            "applicability_evidence_ids": [],
            "valid_at": None,
            "checks": [],
            "reason": "Synthetic multiple exact authority sources",
            "basis_evidence_ids": evidence,
        }
    )
    current = w["client"].get(w["requirement_base"] + "/" + w["inventory"]["manifest"]["id"])
    assert current.status_code == 200
    response = append_inventory(w, tag=current.headers["etag"])
    assert response.status_code == 201, response.text
    inventory = response.json()
    selected = next(r for r in inventory["manifest"]["requirements"] if r["rule_id"] == rule)
    request = deepcopy(w["request"])
    request.update(inventory_id=inventory["manifest"]["id"], inventory_digest=inventory["digest"])
    request["rule_scopes"].append(
        {
            "rule_id": rule,
            "rule_digest": selected["rule_digest"],
            "selection": "include",
            "part_ids": ["tech", "appendix/table"],
            "reason": "Synthetic complete multi-source declaration",
        }
    )
    return w | {"inventory": inventory, "request": request, "multi_source_rule": rule}


def expected(w):
    return material._expected({"scope": w["saved_scope"]})


def parse(w, **changes):
    return parses.observe(
        w["database"]["parse_verifier"],
        **(
            {
                "bid_id": w["technical_scope"][0],
                "expected_documents": expected(w),
                "expected_method_digest": parses.method_digest(),
            }
            | changes
        ),
    )


def collect(w, url, render=None, **changes):
    def default(raw, document):
        assert all(
            w["database"][key].info.transaction_status == TransactionStatus.IDLE
            for key in ("scope_verifier", "original_verifier", "parse_verifier")
        )
        return assets.render_static_pdf(
            raw,
            document_version_id=document["document_version_id"],
            expected_source_digest=document["source_digest"],
            expected_source_size=document["source_byte_size"],
            expected_method_digest=assets.render_method_digest(),
        )

    args = {
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "expected_method_digest": material.method_digest(),
        "profile": "development_s3",
        "url_for_locator": url,
        "render_page_assets": default if render is None else render,
        "expected_render_method_digest": assets.render_method_digest(),
    } | changes
    return asyncio.run(
        material.collect(
            w["database"]["scope_verifier"],
            w["database"]["original_verifier"],
            w["database"]["parse_verifier"],
            **args,
        )
    )


def test_native_full_material_preserves_multi_source_bands_exclusions_and_geometry(wire):
    w, state, url = wire
    result = collect(w, url)
    assert result.material["scope"] == w["saved_scope"]
    rules = result.material["scope"]["manifest"]["preview"]["manifest"]["rules"]
    assert len(rules) == 4 and any(r["selection"] == "exclude" for r in rules)
    multi = next(r for r in rules if r["rule_id"] == w["multi_source_rule"])
    assert len(multi["source_evidence"]) == 3
    assert multi["rule_snapshot"]["conditions"] == ["condition A", "condition B"]
    assert multi["rule_snapshot"]["exceptions"] == ["exception A", "exception B"]
    assert len(multi["rule_snapshot"]["bands"]) == 2
    assert result.metadata["document_count"] == 2 and result.metadata["physical_page_count"] == 4
    assert len(result.originals) == 2 and state["attempts"] == 2
    assert len(result.material["native_documents"]) == 2
    assert any(
        b["structure"] is not None for d in result.material["native_documents"] for b in d["blocks"]
    )
    assert result.metadata["material_digest"] == digest(result.material)
    assert result.metadata["digest"] == digest(
        {k: v for k, v in result.metadata.items() if k != "digest"}
    )
    public = json.dumps(result.metadata)
    assert (
        "Synthetic multi-source rule" not in public
        and "Synthetic multi-source rule" not in repr(result)
    )
    for flag in (
        "renderer_boundary_verified",
        "visual_readability_verified",
        "necessary_scope_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    ):
        assert result.metadata[flag] is False
    directory = os.environ.get("FUSION_CURRENT_MATERIAL_EVIDENCE")
    if directory:
        out = Path(directory)
        (out / "current-material-native-proof.json").write_text(
            json.dumps(
                {
                    "observation": result.metadata,
                    "synthetic_content": True,
                    "in_process_renderer_for_mechanism_test": True,
                    "wire_gets": state["attempts"],
                    "preserved_rules": 4,
                    "preserved_multi_source_evidence": 3,
                    "preserved_bands": 2,
                    "preserved_excluded_rules": 1,
                    "body_and_locator_exported": False,
                    "real_oss_or_s3_reads": 0,
                    "formal_binding_registered": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # Explicit synthetic artifacts for separate host Compose-renderer
        # acceptance. They are never part of the public observation or Git body.
        (out / "synthetic-current-material-original.pdf").write_bytes(w["io"]["data"])
        (out / "synthetic-current-material-render-plan.json").write_text(
            json.dumps(
                {
                    "native_observation_digest": result.metadata["digest"],
                    "synthetic_content": True,
                    "documents": [
                        {k: v for k, v in row.items() if k != "blocks"}
                        for row in result.material["native_documents"]
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "field",
    ["parser_digest", "config_digest", "parse_digest", "parse_run_id", "document_version_id"],
)
def test_exact_parse_identity_cannot_be_substituted(saved, field):
    docs = expected(saved)
    docs[0][field] = str(uuid4()) if field.endswith("_id") else "0" * 64
    with pytest.raises(parses.CurrentParseMaterialError):
        parse(saved, expected_documents=docs)


def test_native_material_role_cannot_read_locator_or_labels(saved):
    verifier = saved["database"]["parse_verifier"]
    for query in (
        "SELECT object_key FROM design.blobs",
        "SELECT * FROM design.outcomes",
        "SELECT * FROM retrieval.chunks",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            verifier.execute(query)
    assert parse(saved).metadata["native_parse_content_reverified"]


def test_borrowed_transaction_and_owner_reject(saved):
    with saved["database"]["parse_verifier"].transaction():
        with pytest.raises(parses.CurrentParseMaterialError, match="IDLE_CONNECTION_REQUIRED"):
            parse(saved)
    with pytest.raises(parses.CurrentParseMaterialError, match="INDEPENDENT_LOGIN_REQUIRED"):
        parses.observe(
            saved["database"]["owner"],
            bid_id=saved["technical_scope"][0],
            expected_documents=expected(saved),
            expected_method_digest=parses.method_digest(),
        )


def test_frozen_text_geometry_must_match_actual_native_records(saved):
    native = parse(saved)
    facts = {"scope": deepcopy(saved["saved_scope"])}
    document = facts["scope"]["manifest"]["preview"]["manifest"]["documents"][0]
    document["blocks"][0]["text_content"] = "synthetic substituted text"
    with pytest.raises(material.CurrentMaterialError, match="FROZEN_PARSE_CONTENT_MISMATCH"):
        material._check_frozen(facts, native)


def test_missing_or_ambiguous_exact_parse_is_not_guessed(saved):
    facts = {"scope": deepcopy(saved["saved_scope"])}
    docs = facts["scope"]["manifest"]["preview"]["manifest"]["documents"]
    docs[0]["parse"]["status"] = "not_frozen"
    with pytest.raises(material.CurrentMaterialError, match="EXACT_PARSE_REQUIRED"):
        material._expected(facts)
    docs[0]["parse"]["status"] = "frozen"
    duplicate = deepcopy(docs[0])
    duplicate["parse"]["parse_run_id"] = str(uuid4())
    docs.append(duplicate)
    with pytest.raises(material.CurrentMaterialError, match="DOCUMENT_PARSE_AMBIGUOUS"):
        material._expected(facts)


@pytest.mark.parametrize("mutation", ["withdraw", "close"])
def test_change_during_render_rejects_entire_material(wire, mutation):
    w, state, url = wire

    def rendering(raw, document):
        owner = w["database"]["owner"]
        if mutation == "close":
            owner.execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                (w["technical_scope"][0],),
            )
        else:
            root = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
                "source_id"
            ]
            owner.execute(
                "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                (root,),
            )
        return assets.render_static_pdf(
            raw,
            document_version_id=document["document_version_id"],
            expected_source_digest=document["source_digest"],
            expected_source_size=document["source_byte_size"],
            expected_method_digest=assets.render_method_digest(),
        )

    with pytest.raises((parses.CurrentParseMaterialError, scope.CurrentScopeError)) as caught:
        collect(w, url, rendering)
    assert "SOURCE" in str(caught.value) or "NOT_CURRENT_PREBID" in str(caught.value)


def test_render_method_and_total_asset_limits_reject(wire, monkeypatch):
    w, state, url = wire
    with pytest.raises(material.CurrentMaterialError, match="RENDER_METHOD_MISMATCH"):
        collect(w, url, expected_render_method_digest="0" * 64)
    monkeypatch.setattr(material, "MAX_ASSET_BYTES", 1)
    with pytest.raises(material.CurrentMaterialError, match="ASSET_LIMIT"):
        collect(w, url)


def test_parse_text_limits_run_before_material_return(saved, monkeypatch):
    monkeypatch.setattr(sources, "MAX_TEXT_BYTES", 1)
    with pytest.raises(parses.CurrentParseMaterialError, match="PARSE_LIMIT"):
        parse(saved)


@pytest.mark.parametrize("field,value", [("width", "401"), ("height", "501"), ("rotation", 90)])
def test_rendered_geometry_cannot_be_bound_to_another_parse(wire, field, value):
    w, state, url = wire
    native = parse(w)
    expected_document = expected(w)[0]
    bundle = assets.render_static_pdf(
        w["io"]["data"],
        document_version_id=expected_document["document_version_id"],
        expected_source_digest=expected_document["source_digest"],
        expected_source_size=expected_document["source_byte_size"],
        expected_method_digest=assets.render_method_digest(),
    )
    pages = deepcopy(native.documents[0]["pages"])
    pages[0][field] = value
    with pytest.raises(material.CurrentMaterialError, match="PAGE_GEOMETRY_MISMATCH"):
        material._check_page_geometry(bundle.manifest, pages)
