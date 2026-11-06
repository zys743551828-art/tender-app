"""Real nonowner API against a disposable local PostgreSQL; synthetic inputs only."""
# ruff: noqa: F811

import json
import os

import pytest
from psycopg.types.json import Jsonb
from test_bid_package_api import attach, database, world  # noqa: F401
from test_bid_package_repository import add_document
from test_stable_lot_identity import api, headers, uid  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_PACKAGE_API_ADMIN_DSN"), reason="isolated PG17 required"
)


def test_partial_confirmation_rechecks_and_never_grants_review_or_model(world):
    owner = world["database"]["owner"]
    bid = world["scope"].bid_id
    member = world["member"]
    material = uid()
    partial_parse = uid()
    with owner.transaction():
        owner.execute("SET LOCAL search_path TO design,public")
        official = add_document(owner, world["scope"], world["actor"])
        attach(owner, bid, world["actor"], official, role="official_result")
        owner.execute(
            "INSERT INTO design.material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,%s,%s)",
            (material, bid, Jsonb({}), "d" * 64),
        )
        owner.execute(
            "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'body',0)",
            (material, bid, member.document_version_id),
        )
        owner.execute(
            "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'official_result',0)",
            (material, bid, official.document_version_id),
        )
        owner.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s WHERE bid_id=%s", (material, bid)
        )
        owner.execute(
            """INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps)
            SELECT %s,bid_id,document_version_id,%s,config_digest,page_count,'partial',%s FROM design.parse_runs WHERE id=%s""",
            (
                partial_parse,
                "e" * 64,
                Jsonb([{"physical_page": 1, "code": "OCR_UNVERIFIED"}]),
                member.parse.parse_run_id,
            ),
        )
        owner.execute(
            """INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps)
            SELECT bid_id,%s,physical_page,width,height,rotation,
            CASE WHEN physical_page=1 THEN 'partial' ELSE quality END,
            CASE WHEN physical_page=1 THEN %s::jsonb ELSE gaps END
            FROM design.pages WHERE parse_id=%s""",
            (partial_parse, Jsonb(["OCR_LOW_CONFIDENCE"]), member.parse.parse_run_id),
        )
        owner.execute(
            """INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest)
            SELECT gen_random_uuid(),bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest
            FROM design.evidence_blocks WHERE parse_id=%s""",
            (partial_parse, member.parse.parse_run_id),
        )
    client = world["client"]
    base = f"/api/v1/bids/{bid}/partial-page-selections"
    body = {
        "document_version_id": member.document_version_id,
        "parse_run_id": partial_parse,
        "first_page": 1,
        "last_page": 1,
        "purpose": "technical_reference",
        "confirmed": True,
    }
    assert (
        client.post(base, json=body | {"confirmed": False}, headers=headers(world)).status_code
        == 422
    )
    assert (
        client.post(base, json=body | {"last_page": 3}, headers=headers(world)).status_code == 409
    )
    assert (
        client.post(
            base,
            json=body
            | {
                "document_version_id": official.document_version_id,
                "parse_run_id": official.parse.parse_run_id,
            },
            headers=headers(world),
        ).status_code
        == 404
    )
    assert (
        client.post(base, json=body, headers={"Origin": "http://identity-v2.test"}).status_code
        == 403
    )
    key = uid()
    result = client.post(base, json=body, headers=headers(world, key=key))
    assert result.status_code == 201, result.json()
    record = result.json()
    assert record["confirmed_by"] == world["actor"]
    assert record["manual_confirmation_recorded"] is True
    assert record["model_execution_allowed"] is record["formal_qualification"] is False
    proof = record["proof"]["manifest"]
    assert proof["coverage"] == "partial"
    assert proof["selected_pages"][0]["gaps"] == ["OCR_LOW_CONFIDENCE"]
    assert proof["omitted_ranges"] == [{"first_page": 2, "last_page": 2}]
    assert all(block["physical_page"] == 1 for block in proof["selected_blocks"])
    assert "synthetic page" not in json.dumps(record)
    again = client.post(base, json=body, headers=headers(world, key=key))
    assert again.status_code == 201 and again.json()["id"] == record["id"]
    assert (
        client.post(base, json=body | {"last_page": 2}, headers=headers(world, key=key)).status_code
        == 409
    )
    read = client.get(base + "/" + record["id"])
    assert read.status_code == 200 and read.json()["proof"] == record["proof"]
    scoped = client.get(base + "/" + record["id"] + "/evidence")
    assert scoped.status_code == 200, scoped.text
    evidence = scoped.json()
    assert evidence["proof_digest"] == record["proof"]["digest"]
    assert evidence["model_execution_allowed"] is evidence["formal_qualification"] is False
    assert {item["id"] for item in evidence["items"]} == {
        item["id"] for item in proof["selected_blocks"]
    }
    assert all(item["physical_page"] == 1 for item in evidence["items"])
    listing = client.get(base, params={"document_version_id": member.document_version_id})
    assert listing.status_code == 200 and [item["id"] for item in listing.json()["items"]] == [
        record["id"]
    ]
    assert client.get(base.replace(bid, uid()) + "/" + record["id"]).status_code == 404
    from fastapi.testclient import TestClient

    with TestClient(world["app"]) as anonymous:
        assert anonymous.get(base + "/" + record["id"]).status_code == 401
        assert anonymous.get(base + "/" + record["id"] + "/evidence").status_code == 401
    replacement = uid()
    with owner.transaction():
        owner.execute(
            "INSERT INTO design.material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,2,%s,%s)",
            (replacement, bid, Jsonb({}), "f" * 64),
        )
        owner.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s WHERE bid_id=%s",
            (replacement, bid),
        )
    old = client.get(base + "/" + record["id"])
    assert old.status_code == 200 and old.json()["current_material"] is False
    assert client.post(base, json=body, headers=headers(world)).status_code == 409
