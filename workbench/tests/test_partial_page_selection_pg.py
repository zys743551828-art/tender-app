"""Real nonowner API against a disposable local PostgreSQL; synthetic inputs only."""
# ruff: noqa: F811

import json
import os
from hashlib import sha256

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
        tender = add_document(owner, world["scope"], world["actor"])
        attach(owner, bid, world["actor"], tender, role="tender")
        owner.execute(
            """INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest)
            VALUES(%s,%s,%s,1,1,'text',%s,%s,%s,%s)""",
            (
                uid(),
                bid,
                tender.parse.parse_run_id,
                "SYNTHETIC alternate requirement",
                Jsonb([0.1, 0.2, 0.8, 0.9]),
                Jsonb({}),
                sha256(b"SYNTHETIC alternate requirement").hexdigest(),
            ),
        )
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
            "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'tender',0)",
            (material, bid, tender.document_version_id),
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
    # The scoped retrieval itself filters by project, parse and explicit block
    # IDs in PostgreSQL, including when the requested source contains other pages.
    from apps.api.views import evidence_views_selected

    with owner.transaction():
        outside_id = str(
            owner.execute(
                "SELECT id FROM design.evidence_blocks WHERE parse_id=%s AND physical_page=2 LIMIT 1",
                (partial_parse,),
            ).fetchone()["id"]
        )
    selected_ids = [item["id"] for item in proof["selected_blocks"]]
    with world["database"]["owner"].transaction():
        view = evidence_views_selected(owner, bid, partial_parse, selected_ids)
        assert {item["id"] for item in view} == set(selected_ids)
        assert outside_id not in {item["id"] for item in view}
        assert evidence_views_selected(owner, uid(), partial_parse, selected_ids) == []
    listing = client.get(base, params={"document_version_id": member.document_version_id})
    assert listing.status_code == 200 and [item["id"] for item in listing.json()["items"]] == [
        record["id"]
    ]
    assert client.get(base.replace(bid, uid()) + "/" + record["id"]).status_code == 404
    requirement = client.post(
        base,
        json=body
        | {
            "purpose": "requirement_reference",
            "document_version_id": tender.document_version_id,
            "parse_run_id": tender.parse.parse_run_id,
        },
        headers=headers(world),
    )
    assert requirement.status_code == 201
    req_id = requirement.json()["id"]
    candidates = client.get(base + "/candidates")
    assert candidates.status_code == 200
    assert {item["id"] for item in candidates.json()["items"]} == {req_id, record["id"]}
    assert all(item["filename"] == "synthetic.pdf" for item in candidates.json()["items"])
    comparison = client.get(base + "/" + req_id + "/compare/" + record["id"])
    assert comparison.status_code == 200, comparison.text
    compare_body = comparison.json()
    assert compare_body["coverage"] == "partial" and compare_body["overall_result"] == "unknown"
    assert compare_body["model_execution_allowed"] is compare_body["formal_qualification"] is False
    assert all(
        item["physical_page"] == 1
        for side in ("requirement", "technical")
        for item in compare_body[side]["evidence"]["items"]
    )
    assert "synthetic page 2" not in json.dumps(compare_body)
    decision_path = base + "/" + req_id + "/compare/" + record["id"] + "/decisions"
    req_evidence = compare_body["requirement"]["evidence"]["items"][0]["id"]
    tech_evidence = compare_body["technical"]["evidence"]["items"][0]["id"]
    decision_body = {
        "item_id": None,
        "expected_revision": 0,
        "requirement_evidence_id": req_evidence,
        "technical_evidence_id": tech_evidence,
        "outcome": "observed_support",
        "reason": "SYNTHETIC human observation",
        "confirmed": True,
    }
    with owner.transaction():
        counts_before = tuple(
            owner.execute(
                f"SELECT count(*) AS n FROM design.{table} WHERE bid_id=%s", (bid,)
            ).fetchone()["n"]
            for table in ("rule_sets", "review_runs", "operations")
        )
    assert (
        client.post(
            decision_path, json=decision_body, headers={"Origin": "http://identity-v2.test"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            decision_path, json=decision_body | {"confirmed": False}, headers=headers(world)
        ).status_code
        == 422
    )
    assert (
        client.post(
            decision_path,
            json=decision_body | {"technical_evidence_id": None},
            headers=headers(world),
        ).status_code
        == 422
    )
    assert (
        client.post(
            decision_path,
            json=decision_body | {"technical_evidence_id": outside_id},
            headers=headers(world),
        ).status_code
        == 422
    )
    decision_key = uid()
    decision = client.post(
        decision_path, json=decision_body, headers=headers(world, key=decision_key)
    )
    assert decision.status_code == 201, decision.text
    observation = decision.json()
    assert observation["origin"] == "human_observation" and observation["coverage"] == "partial"
    assert (
        observation["overall_result"] == "unknown" and observation["formal_qualification"] is False
    )
    assert (
        client.post(
            decision_path, json=decision_body, headers=headers(world, key=decision_key)
        ).json()["id"]
        == observation["id"]
    )
    second_scope = client.post(base, json=body | {"last_page": 2}, headers=headers(world))
    assert second_scope.status_code == 201
    second_path = base + "/" + req_id + "/compare/" + second_scope.json()["id"] + "/decisions"
    assert (
        client.post(
            second_path, json=decision_body, headers=headers(world, key=decision_key)
        ).status_code
        == 409
    )
    revision_body = decision_body | {
        "item_id": observation["item_id"],
        "expected_revision": 1,
        "outcome": "needs_review",
    }
    alternate_req = compare_body["requirement"]["evidence"]["items"][1]["id"]
    assert (
        client.post(
            decision_path,
            json=revision_body | {"requirement_evidence_id": alternate_req},
            headers=headers(world),
        ).status_code
        == 409
    )
    assert (
        client.post(decision_path, json=revision_body, headers=headers(world)).json()["revision"]
        == 2
    )
    assert client.post(decision_path, json=revision_body, headers=headers(world)).status_code == 409
    unresolved = client.post(
        decision_path,
        json=decision_body | {"technical_evidence_id": None, "outcome": "needs_review"},
        headers=headers(world),
    )
    assert unresolved.status_code == 201 and unresolved.json()["overall_result"] == "unknown"
    history = client.get(decision_path)
    assert history.status_code == 200 and history.json()["scope_revalidated"] is True
    assert {item["revision"] for item in history.json()["items"]} == {1, 2}
    with owner.transaction():
        counts_after = tuple(
            owner.execute(
                f"SELECT count(*) AS n FROM design.{table} WHERE bid_id=%s", (bid,)
            ).fetchone()["n"]
            for table in ("rule_sets", "review_runs", "operations")
        )
    assert counts_after == counts_before
    assert all(
        item["actor_id"] == world["actor"]
        and item["requirement_evidence_id"] == req_evidence
        and item["formal_qualification"] is False
        for item in history.json()["items"]
    )
    assert client.get(base + "/" + record["id"] + "/compare/" + req_id).status_code == 409
    assert (
        client.get(base.replace(bid, uid()) + "/" + req_id + "/compare/" + record["id"]).status_code
        == 404
    )
    from packages.rag.indexing import ensure_parse_sources, parse_source_id

    owner.autocommit = False
    try:
        with owner.transaction():
            ensure_parse_sources(owner, bid, partial_parse)
            owner.execute(
                "UPDATE retrieval.source_heads SET status='withdrawn', revision=revision+1 WHERE source_id=%s",
                (parse_source_id(partial_parse),),
            )
    finally:
        owner.autocommit = True
    withdrawn = client.get(base + "/" + req_id + "/compare/" + record["id"])
    assert withdrawn.status_code == 409
    assert withdrawn.json()["code"] == "PARTIAL_COMPARISON_SOURCE_WITHDRAWN"
    assert client.get(decision_path).json()["scope_revalidated"] is False
    assert client.post(decision_path, json=decision_body, headers=headers(world)).status_code == 409
    assert (
        client.post(
            decision_path, json=decision_body, headers=headers(world, key=decision_key)
        ).status_code
        == 409
    )
    from fastapi.testclient import TestClient

    with TestClient(world["app"]) as anonymous:
        assert anonymous.get(base + "/" + record["id"]).status_code == 401
        assert anonymous.get(base + "/" + record["id"] + "/evidence").status_code == 401
        assert anonymous.get(decision_path).status_code == 401
        assert anonymous.post(decision_path, json=decision_body).status_code == 401
    replacement = uid()
    with owner.transaction():
        owner.execute(
            "INSERT INTO design.material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,2,%s,%s)",
            (replacement, bid, Jsonb({}), "f" * 64),
        )
        owner.execute(
            "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'body',0),(%s,%s,%s,'tender',0)",
            (
                replacement,
                bid,
                member.document_version_id,
                replacement,
                bid,
                tender.document_version_id,
            ),
        )
        owner.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s WHERE bid_id=%s",
            (replacement, bid),
        )
    old = client.get(base + "/" + record["id"])
    assert old.status_code == 200 and old.json()["current_material"] is False
    assert client.get(base + "/" + req_id + "/compare/" + record["id"]).status_code == 409
    assert client.post(base, json=body, headers=headers(world)).status_code == 201
