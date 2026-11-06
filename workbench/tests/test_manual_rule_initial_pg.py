"""Disposable PG17 API-role checks of manual initial rules, with synthetic frozen bytes."""
# ruff: noqa: F811

# ruff: noqa: F401
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_bid_package_repository import add_document
from test_bid_package_requirements_api import database
from test_stable_lot_identity import api, catalog, headers, post, validate_response

from packages.domain import storage
from packages.domain.bid_packages import BidScope

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"), reason="requires isolated disposable PG17"
)
RAW = b"SYNTHETIC manual source, not business material"


def test_real_api_role_manual_initial_is_partial_and_preserves_failed_receipt(api, monkeypatch):
    with psycopg.connect(api["database"]["api_dsn"]) as service:
        current, superuser, owner = service.execute(
            "SELECT current_user, r.rolsuper, pg_get_userbyid(d.datdba) "
            "FROM pg_roles r JOIN pg_database d ON d.datname=current_database() "
            "WHERE r.rolname=current_user"
        ).fetchone()
        assert current == "fusion_package_requirements_service"
        assert not superuser and current != owner
    project, lot, round_value, bidder = catalog(api)
    bid = post(
        api,
        "/bids",
        {
            "title": "SYNTHETIC manual initial",
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    ).json()
    bid_id = bid["id"]
    scope = BidScope(project["id"], lot["id"], round_value["id"], bid_id, bidder["id"])
    owner = api["database"]["owner"]
    operation, command = str(uuid4()), str(uuid4())
    with owner.transaction():
        owner.execute("SET LOCAL search_path TO design,public")
        member = add_document(owner, scope, api["actor"], raw=RAW)
        material = str(uuid4())
        owner.execute(
            "INSERT INTO material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,%s,%s)",
            (material, bid_id, Jsonb({}), "3" * 64),
        )
        owner.execute(
            "UPDATE bid_profiles SET current_material_id=%s WHERE bid_id=%s", (material, bid_id)
        )
        owner.execute("UPDATE bids SET material_revision=1 WHERE id=%s", (bid_id,))
        owner.execute(
            "INSERT INTO material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'tender',0)",
            (material, bid_id, member.document_version_id),
        )
        owner.execute(
            "INSERT INTO commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'synthetic-failed-extraction',%s,%s,%s)",
            (command, api["actor"], bid_id, str(uuid4()), "1" * 64),
        )
        owner.execute(
            "INSERT INTO operations(id,bid_id,command_id,kind,input_digest,state,handler_version,finished_at) VALUES(%s,%s,%s,'prepare-review',%s,'failed','synthetic/1',now())",
            (operation, bid_id, command, "2" * 64),
        )
        intent = {
            "request_id": str(uuid4()),
            "trigger": "manual",
            "body_version_id": None,
            "material_snapshot_id": str(material),
            "material_revision": 1,
            "state": "blocked",
            "preparation_kind": "rules",
            "prepare_operation_id": operation,
            "review_id": None,
            "error_code": "RULE_CONDITION_UNGROUNDED",
            "gaps": [],
        }
        owner.execute(
            "UPDATE review_slots SET pending_intent=%s WHERE bid_id=%s", (Jsonb(intent), bid_id)
        )
        block = owner.execute(
            "SELECT id FROM evidence_blocks WHERE parse_id=%s AND physical_page=1",
            (member.parse.parse_run_id,),
        ).fetchone()["id"]
        block2 = owner.execute(
            "SELECT id FROM evidence_blocks WHERE parse_id=%s AND physical_page=2",
            (member.parse.parse_run_id,),
        ).fetchone()["id"]
    monkeypatch.setattr(storage, "get", lambda _key: RAW)
    request = {
        "material_revision": 1,
        "reason": "SYNTHETIC human review",
        "additions": [
            {
                "kind": "mandatory",
                "statement": "synthetic page 1",
                "conditions": [],
                "exceptions": [],
                "scope": {"bid_id": bid_id, "description": "synthetic"},
                "maximum": None,
                "bands": [],
                "evidence_quotes": [{"evidence_id": str(block), "quote": "synthetic page 1"}],
            }
        ],
    }
    client = api["client"]
    etag = client.get(f"/api/v1/bids/{bid_id}").headers["etag"]
    path = f"/api/v1/bids/{bid_id}/manual-rule-set"
    from fastapi.testclient import TestClient

    with TestClient(api["app"]) as anonymous:
        assert anonymous.post(path, json=request).status_code == 401
    assert client.post(path, json=request, headers=headers(api, etag='"stale"')).status_code == 412
    assert (
        client.post(
            path, json=request | {"material_revision": 2}, headers=headers(api, etag=etag)
        ).status_code
        == 409
    )
    bad = {
        **request,
        "additions": [
            {
                **request["additions"][0],
                "evidence_quotes": [{"evidence_id": str(block), "quote": "not in source"}],
            }
        ],
    }
    assert client.post(path, json=bad, headers=headers(api, etag=etag)).status_code == 422
    assert (
        owner.execute(
            "SELECT current_rule_set_id FROM design.bid_profiles WHERE bid_id=%s", (bid_id,)
        ).fetchone()["current_rule_set_id"]
        is None
    )
    h = headers(api, etag=etag)
    response = client.post(f"/api/v1/bids/{bid_id}/manual-rule-set", json=request, headers=h)
    assert response.status_code == 201, response.text
    validate_response(api, "/api/v1/bids/{bid_id}/manual-rule-set", "post", response)
    value = response.json()
    assert value["coverage"] == "partial" and len(value["rules"]) == 1
    assert value["rules"][0]["origin_kind"] == "human_added"
    assert value["rules"][0]["confirmation"] == "confirmed"
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.bid_package_requirement_extraction_runs WHERE bid_id=%s",
            (bid_id,),
        ).fetchone()["n"]
        == 0
    )
    replay = client.post(f"/api/v1/bids/{bid_id}/manual-rule-set", json=request, headers=h)
    assert replay.status_code == 201 and replay.json() == value
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.effect_receipts WHERE operation_id=%s", (operation,)
        ).fetchone()["n"]
        == 0
    )
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.audit_entries WHERE bid_id=%s AND event_type='rules.manual_initialized'",
            (bid_id,),
        ).fetchone()["n"]
        == 1
    )
    assert client.post(
        f"/api/v1/bids/{bid_id}/manual-rule-set", json=request, headers=headers(api, etag=etag)
    ).status_code in (409, 412)
    addition2 = {
        **request["additions"][0],
        "statement": "synthetic page 2",
        "evidence_quotes": [{"evidence_id": str(block2), "quote": "synthetic page 2"}],
    }
    corrected = client.post(
        f"/api/v1/bids/{bid_id}/rule-set-corrections",
        json={
            "base_rule_set_id": value["id"],
            "reason": "SYNTHETIC next review",
            "additions": [addition2],
        },
        headers=headers(api, etag=response.headers["etag"]),
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["coverage"] == "partial"
    assert {row["origin_kind"] for row in corrected.json()["rules"]} == {
        "human_added",
        "carried_human",
    }
    assert (
        owner.execute(
            "SELECT coverage FROM design.rule_sets WHERE id=%s", (value["id"],)
        ).fetchone()["coverage"]
        == "partial"
    )
