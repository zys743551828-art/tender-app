"""Real nonowner/read-only preview; never a formal review or paid model test."""

# ruff: noqa: F401,F811
import os
from dataclasses import replace

import pytest
from test_bid_package_requirements_api import (
    api,
    attempt_body,
    counts,
    database,
    headers,
    inventory,
    requirements,
    uid,
    world,
)

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.bid_package_repository import load_revision, save_revision
from packages.domain.bid_packages import ParseIdentity
from packages.domain.review_identity import digest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"), reason="requires grouped isolated PG"
)


def prepare(w):
    result = inventory(w)
    assert result.status_code == 201, result.text
    saved = result.json()
    body = {
        "package_digest": saved["manifest"]["package_digest"],
        "inventory_digest": saved["digest"],
        "coverage_attempt_id": None,
        "coverage_digest": None,
    }
    return result, saved, body


def url(w, inv):
    return w["requirement_base"] + "/" + inv["manifest"]["id"] + "/review-input-preview"


def check(w, inv, body, **kwargs):
    return w["client"].post(
        url(w, inv),
        json=body,
        headers={k: v for k, v in headers(w).items() if k.lower() != "idempotency-key"},
        **kwargs,
    )


def test_exact_preview_never_chooses_current_body_or_writes_commands_jobs(requirements):
    w = requirements
    _, inv, body = prepare(w)
    before = counts(w)
    c = w["database"]["owner"]
    before_jobs = c.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"]
    response = check(w, inv, body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert valid("PackageReviewInputPreview", value)
    assert value["manifest"]["target"]["digest"] == inv["manifest"]["package_digest"]
    assert value["manifest"]["authority"]["digest"] == inv["manifest"]["authority_digest"]
    assert value["manifest"]["inventory"] == inv
    assert value["manifest"]["coverage"] is None
    assert digest(value["manifest"]) == value["digest"]
    assert value["review_ready"] is value["launch_available"] is False
    assert "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN" in value["blockers"]
    assert "PACKAGE_REVIEW_EXTRACTION_UNPROVEN" in value["blockers"]
    assert "PACKAGE_REVIEW_EXECUTOR_NOT_READY" in value["blockers"]
    assert check(w, inv, body).json() == value
    assert counts(w) == before
    assert c.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"] == before_jobs


def test_selected_coverage_is_not_silently_replaced_by_newest_attempt(requirements):
    w = requirements
    _, inv, body = prepare(w)
    path = w["requirement_base"] + "/" + inv["manifest"]["id"] + "/coverage-attempts"
    old = w["client"].post(path, json=attempt_body(w, inv, state="parse_gap"), headers=headers(w))
    new = w["client"].post(path, json=attempt_body(w, inv, state="missing"), headers=headers(w))
    assert old.status_code == new.status_code == 201
    selected = old.json()
    body |= {
        "coverage_attempt_id": selected["manifest"]["id"],
        "coverage_digest": selected["digest"],
    }
    response = check(w, inv, body)
    assert response.status_code == 200, response.text
    assert response.json()["manifest"]["coverage"] == selected


@pytest.mark.parametrize("field", ["package_digest", "inventory_digest", "coverage_digest"])
def test_digest_tampering_rejected_without_business_writes(requirements, field):
    w = requirements
    _, inv, body = prepare(w)
    body[field] = "0" * 64
    before = counts(w)
    response = check(w, inv, body)
    assert response.status_code == 422, response.text
    assert counts(w) == before


def test_missing_coverage_does_not_fall_back_to_any_history(requirements):
    w = requirements
    _, inv, body = prepare(w)
    body |= {"coverage_attempt_id": uid(), "coverage_digest": "0" * 64}
    response = check(w, inv, body)
    assert response.status_code == 404
    assert response.json()["code"] == "PACKAGE_COVERAGE_ATTEMPT_NOT_FOUND"


def test_coverage_from_another_inventory_is_not_adopted(requirements):
    w = requirements
    first, old, _ = prepare(w)
    path = w["requirement_base"] + "/" + old["manifest"]["id"] + "/coverage-attempts"
    saved = w["client"].post(path, json=attempt_body(w, old, state="missing"), headers=headers(w))
    assert saved.status_code == 201
    newer = inventory(w, tag=first.headers["etag"])
    assert newer.status_code == 201
    current = newer.json()
    body = {
        "package_digest": current["manifest"]["package_digest"],
        "inventory_digest": current["digest"],
        "coverage_attempt_id": saved.json()["manifest"]["id"],
        "coverage_digest": saved.json()["digest"],
    }
    response = check(w, current, body)
    assert response.status_code == 404
    assert response.json()["code"] == "PACKAGE_COVERAGE_ATTEMPT_NOT_FOUND"


def test_inventory_from_another_package_is_not_visible(requirements):
    from test_bid_package_api import create

    w = requirements
    _, inv, body = prepare(w)
    other = create(w)
    assert other.status_code == 201
    m = other.json()["manifest"]
    foreign = w | {
        "requirement_base": w["base"]
        + "/"
        + m["package_id"]
        + "/revisions/"
        + m["revision_id"]
        + "/requirement-inventories"
    }
    response = check(foreign, inv, body)
    assert response.status_code == 404
    assert response.json()["code"] == "PACKAGE_REQUIREMENT_INVENTORY_NOT_FOUND"


def test_old_selected_input_stays_identical_when_head_changes(requirements):
    w = requirements
    _, inv, body = prepare(w)
    old = check(w, inv, body).json()
    c = w["database"]["owner"]
    m = w["own"]["manifest"]
    original = load_revision(c, w["scope"].bid_id, m["revision_id"])
    newer = original.next_revision(uid(), original.members)
    save_revision(c, newer, expected_digest=original.manifest_digest)
    response = check(w, inv, body)
    assert response.status_code == 200, response.text
    assert response.json()["digest"] == old["digest"]
    assert response.json()["manifest"] == old["manifest"]
    assert "PACKAGE_REVIEW_PACKAGE_STALE" in response.json()["blockers"]


def test_source_withdrawal_and_project_close_are_observations_not_historical_rewrites(requirements):
    w = requirements
    _, inv, body = prepare(w)
    original = check(w, inv, body).json()
    c = w["database"]["owner"]
    c.execute(
        "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
        (w["sources"][0],),
    )
    c.execute("UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (w["scope"].bid_id,))
    response = check(w, inv, body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["digest"] == original["digest"]
    assert value["manifest"] == original["manifest"]
    assert {
        "PROJECT_WORK_CLOSED",
        "PACKAGE_REVIEW_SOURCE_CHANGED",
        "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE",
    } <= set(value["blockers"])


@pytest.mark.parametrize("kind", ["gap", "unfrozen"])
def test_unknown_member_or_physical_hole_cannot_disappear_from_preflight(requirements, kind):
    w = requirements
    c = w["database"]["owner"]
    original = load_revision(c, w["scope"].bid_id, w["own"]["manifest"]["revision_id"])
    member = original.members[0]
    changed = (
        replace(member, parts=(replace(member.parts[0], last_page=1),))
        if kind == "gap"
        else replace(
            member,
            page_count=None,
            parts=(),
            parse=ParseIdentity("not_frozen", reason="explicit synthetic unknown"),
        )
    )
    newer = original.next_revision(uid(), (changed,))
    save_revision(c, newer, expected_digest=original.manifest_digest)
    w = w | {
        "requirement_base": w["base"]
        + "/"
        + original.package_id
        + "/revisions/"
        + newer.revision_id
        + "/requirement-inventories",
        "inventory_body": w["inventory_body"] | {"mappings": []},
    }
    _, inv, body = prepare(w)
    response = check(w, inv, body)
    assert response.status_code == 200, response.text
    value = response.json()
    if kind == "gap":
        assert value["physical_page_gaps"] == [
            {"role": "target", "member_id": member.member_id, "first_page": 2, "last_page": 2}
        ]
        assert "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP" in value["blockers"]
    else:
        assert "PACKAGE_REVIEW_MEMBERS_UNPROVEN" in value["blockers"]
        assert (
            value["manifest"]["target"]["manifest"]["members"][0]["parse"]["status"] == "not_frozen"
        )


def test_preview_requires_session_csrf_and_strict_shape(requirements):
    w = requirements
    _, inv, body = prepare(w)
    r = w["client"].post(url(w, inv), json=body)
    assert r.status_code == 403
    forged = check(w, inv, body | {"review_ready": True})
    assert forged.status_code == 422
