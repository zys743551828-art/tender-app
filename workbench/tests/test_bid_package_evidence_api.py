"""Actual nonowner/full BASE_SQL discovery in the grouped checks requirements database."""
# ruff: noqa: F401,F811

import os
from copy import deepcopy

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_bid_package_api import create, world
from test_bid_package_requirements_api import database
from test_stable_lot_identity import api, catalog, headers, post, uid, validate_response

from packages.domain.runtime import sha
from packages.identity import pagination

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires grouped isolated requirements PG17",
)


def package(world, item=None):
    response = create(world, body={"kind": "bid", "members": [item or world["item"]]})
    assert response.status_code == 201, response.text
    manifest = response.json()["manifest"]
    return response, world["base"] + "/" + manifest["package_id"] + "/revisions/" + manifest[
        "revision_id"
    ] + "/evidence"


def test_only_exact_frozen_parse_and_member_part_pages_not_newest_run(world):
    item = deepcopy(world["item"])
    item["parts"][0]["last_page"] = 1
    stored, path = package(world, item)
    old_parse = world["member"].parse.parse_run_id
    c = world["database"]["owner"]
    new_parse, new_evidence = uid(), uid()
    with c.transaction():
        c.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps,created_at) SELECT %s,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps,now()+interval '1 hour' FROM design.parse_runs WHERE id=%s",
            (new_parse, old_parse),
        )
        c.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) SELECT bid_id,%s,physical_page,width,height,rotation,quality,gaps FROM design.pages WHERE parse_id=%s",
            (new_parse, old_parse),
        )
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest) SELECT %s,bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest FROM design.evidence_blocks WHERE parse_id=%s AND physical_page=1",
            (new_evidence, new_parse, old_parse),
        )
    response = world["client"].get(path)
    assert response.status_code == 200, response.text
    validate_response(
        world,
        "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/evidence",
        "get",
        response,
    )
    value = response.json()
    assert value["package_digest"] == stored.json()["digest"]
    assert len(value["items"]) == 1
    assert value["items"][0]["parse_run_id"] == old_parse
    assert value["items"][0]["physical_page"] == 1
    assert value["items"][0]["id"] != new_evidence
    assert set(value["items"][0]) == {
        "id",
        "document_version_id",
        "parse_run_id",
        "physical_page",
        "part_ids",
    }
    with psycopg.connect(world["database"]["api_dsn"]) as api_c:
        role = api_c.execute(
            "SELECT r.rolsuper,pg_has_role(r.oid,n.nspowner,'USAGE') FROM pg_roles r JOIN pg_namespace n ON n.nspname='design' WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False)


def test_shared_parts_deduplicate_evidence_while_retaining_every_matching_part(world):
    item = deepcopy(world["item"])
    item["purposes"] = ["technical", "business"]
    item["parts"] = [
        {**item["parts"][0], "part_id": "alpha", "shared_attachment": True},
        {
            **item["parts"][0],
            "part_id": "omega",
            "category": "business",
            "last_page": 1,
            "shared_attachment": True,
        },
    ]
    _, path = package(world, item)
    response = world["client"].get(path)
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 2 and len({r["id"] for r in rows}) == 2
    assert {r["physical_page"]: r["part_ids"] for r in rows} == {
        1: ["alpha", "omega"],
        2: ["alpha"],
    }


def test_unfrozen_member_returns_no_inferred_latest_evidence(world):
    item = {k: v for k, v in world["item"].items() if k != "parse_run_id"}
    item["parts"] = []
    _, path = package(world, item)
    response = world["client"].get(path)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [] and response.json()["next_cursor"] is None


def test_signed_keyset_is_exact_revision_package_digest_bound_and_history_survives_new_head(world):
    stored, path = package(world)
    first = world["client"].get(path, params={"limit": 1})
    assert first.status_code == 200, first.text
    token = first.json()["next_cursor"]
    assert first.json()["has_more"] and token
    second = world["client"].get(path, params={"limit": 1, "cursor": token})
    assert second.status_code == 200 and not second.json()["has_more"]
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]
    item = deepcopy(world["item"])
    item["parts"][0]["last_page"] = 1
    append = world["client"].post(
        world["base"] + "/" + stored.json()["manifest"]["package_id"] + "/revisions",
        json={"members": [item]},
        headers=headers(world, etag=stored.headers["etag"]),
    )
    assert append.status_code == 201, append.text
    new_path = (
        world["base"]
        + "/"
        + append.json()["manifest"]["package_id"]
        + "/revisions/"
        + append.json()["manifest"]["revision_id"]
        + "/evidence"
    )
    mismatch = world["client"].get(new_path, params={"cursor": token})
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "INVALID_CURSOR"
    _, other_path = package(world)
    mismatch = world["client"].get(other_path, params={"cursor": token})
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "INVALID_CURSOR"
    assert world["client"].get(path).json()["items"] == sorted(
        first.json()["items"] + second.json()["items"], key=lambda r: r["id"]
    )
    assert world["client"].get(path).json()["package_digest"] == stored.json()["digest"]
    malformed = world["client"].get(path, params={"cursor": token + ".invalid"})
    assert malformed.status_code == 422 and malformed.json()["code"] == "INVALID_CURSOR"
    wrong_digest_scope = sha(
        {
            "directory": "bid-package-evidence/1",
            "bid_id": world["scope"].bid_id,
            "package_id": stored.json()["manifest"]["package_id"],
            "revision_id": stored.json()["manifest"]["revision_id"],
            "package_digest": "0" * 64,
        }
    )
    wrong_digest_token = pagination.encode(wrong_digest_scope, ["", first.json()["items"][0]["id"]])
    mismatch = world["client"].get(path, params={"cursor": wrong_digest_token})
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "INVALID_CURSOR"


def test_auth_scope_and_bounded_input_do_not_disclose_other_packages(world):
    _, path = package(world)
    with TestClient(world["app"]) as anonymous:
        assert anonymous.get(path).status_code == 401
    assert world["client"].get(path.replace(world["scope"].bid_id, uid(), 1)).status_code == 404
    package_id = path.split("/packages/")[1].split("/")[0]
    assert world["client"].get(path.replace(package_id, uid(), 1)).status_code == 404
    for params in ({"limit": 0}, {"limit": 101}, {"cursor": "x" * 4097}):
        assert world["client"].get(path, params=params).status_code == 422
