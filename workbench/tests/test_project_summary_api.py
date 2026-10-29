"""Actual restricted API batch; exact counts, read-only effects and closed response protocol."""
# ruff: noqa: F401,F811

import os

import pytest
from test_bid_package_api import create
from test_bid_package_requirements_api import api, counts, database, requirements, uid, world
from test_stable_lot_identity import post

from packages.contracts.project_summary_api import validate

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires grouped independent PostgreSQL",
)
PATH = "/api/v1/project-work-summaries"


def read(w, *identities):
    return w["client"].get(PATH, params=[("bid_id", identity) for identity in identities])


def test_package_counts_are_current_directory_metadata_and_no_business_writes(requirements):
    w = requirements
    before = counts(w)
    response = read(w, w["scope"].bid_id)
    assert response.status_code == 200, response.text
    validate("ProjectWorkSummaryBatch", response.json())
    item = response.json()["items"][0]
    assert item["package_counts"] == {"authority": 1, "bid": 1}
    assert item["head_members"] == {"total": 2, "parse_not_frozen": 0}
    assert item["next_action"]["action"] == "choose_package_revision"
    assert item["critical_risk_count"] is item["predicted_score"] is None
    assert counts(w) == before


def test_empty_directory_has_zero_registered_packages_but_unknown_risk(world):
    w = world
    response = read(w, w["scope"].bid_id)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["package_counts"] == {"authority": 0, "bid": 0}
    assert item["critical_risk_count"] is None and item["other_risk_count"] is None
    assert item["next_action"]["action"] == "assemble_packages"


def test_bounded_batch_preserves_selection_order_and_missing_item_fails_closed(world):
    w = world
    other = post(w, "/bids", {"title": "synthetic summary second project"}).json()["id"]
    first = w["scope"].bid_id
    response = read(w, other, first)
    assert response.status_code == 200, response.text
    assert [item["bid_id"] for item in response.json()["items"]] == [other, first]
    assert read(w, first, first).status_code == 422
    assert read(w, first, uid()).status_code == 404
    assert read(w, *[uid() for _ in range(21)]).status_code == 422


def test_summary_auth_is_required_and_read_does_not_change_bid_cas(world):
    w = world
    path = "/api/v1/bids/" + w["scope"].bid_id
    before = w["client"].get(path)
    assert read(w, w["scope"].bid_id).status_code == 200
    assert w["client"].get(path).headers["etag"] == before.headers["etag"]
    from fastapi.testclient import TestClient

    with TestClient(w["app"]) as anonymous:
        assert anonymous.get(PATH, params={"bid_id": w["scope"].bid_id}).status_code == 401


def test_not_frozen_parse_is_counted_from_exact_registered_head(requirements):
    w = requirements
    member = {key: value for key, value in w["item"].items() if key != "parse_run_id"} | {
        "parts": []
    }
    created = create(w, body={"kind": "bid", "members": [member]})
    assert created.status_code == 201, created.text
    response = read(w, w["scope"].bid_id)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["package_counts"] == {"authority": 1, "bid": 2}
    assert item["head_members"] == {"total": 3, "parse_not_frozen": 1}
    assert item["next_action"]["action"] == "inspect_package_parses"
    assert item["critical_risk_count"] is None
