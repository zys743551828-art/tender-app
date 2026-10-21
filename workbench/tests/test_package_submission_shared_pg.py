"""Actual package submission HTTP routes and their shared read/metrics consumers."""
# ruff: noqa: F401,F811

import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_bid_package_submissions_pg import (
    api,
    catalog,
    database,
    exact,
    headers,
    inventory,
    requirements,
    uid,
    world,
)
from test_package_outcomes_pg import setup as outcome_case
from test_stable_lot_identity import validate_response

from packages.domain.runtime import connection, etag
from packages.metrics import records, snapshots, sources
from packages.rag.indexing import original_source_id
from packages.research import outcomes

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner package shared-consumer PG17 required",
)
BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"


def base(w, selection=None):
    selection = selection or w["selection"]
    return BASE.format(bid_id=w["scope"].bid_id, **selection)


def preview(w, selection=None):
    selection = selection or w["selection"]
    response = w["client"].post(
        base(w, selection) + "/submission-preview", json=selection, headers=headers(w)
    )
    assert response.status_code == 200, response.text
    assert {directive.strip() for directive in response.headers["cache-control"].split(",")} == {
        "private",
        "no-store",
    }
    validate_response(w, BASE + "/submission-preview", "post", response)
    return response.json()


def body(w, preview, *, correction=False):
    head = preview["current_submission_head"]
    return {
        "kind": "offline_fact",
        "selection": preview["selection_request"],
        "input_digest": preview["input_digest"],
        "evidence": w["attachment"],
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "explanation": "Synthetic exact package submitted outside this system.",
        "expected_head": {key: head[key] for key in ("id", "revision")} if correction else None,
        "correction_reason": "Synthetic correction to the actual whole-package revision."
        if correction
        else None,
    }


def register_http(w, *, selection=None):
    observed = preview(w, selection)
    request = body(w, observed)
    key = uid()
    response = w["client"].post(
        base(w, selection) + "/submissions",
        json=request,
        headers=headers(w, key=key, etag=observed["bid_etag"]),
    )
    assert response.status_code == 201, response.text
    validate_response(w, BASE + "/submissions", "post", response)
    return observed, request, key, response


def metrics(w, **query):
    response = w["client"].get("/api/v1/metrics", params={"bid_ids": w["scope"].bid_id, **query})
    assert response.status_code == 200, response.text
    validate_response(w, "/api/v1/metrics", "get", response)
    return response.json()


def test_http_preview_fact_ack_shared_list_detail_and_idempotency(exact):
    w = exact
    observed = preview(w)
    assert w["io"]["calls"] == []
    assert observed["gate"]["manifest"]["allowed"] is False
    assert observed["selection"]["inventory"] is None
    observed, request, key, response = register_http(w)
    ack = response.json()
    saved = ack["submission"]
    assert saved["subject_kind"] == "bid_package"
    assert saved["body_version_id"] is saved["review_id"] is None
    assert ack["command"]["request"] == request
    assert ack["command"]["if_match"] == observed["bid_etag"]
    calls = list(w["io"]["calls"])
    replay = w["client"].post(
        base(w) + "/submissions",
        json=request,
        headers=headers(w, key=key, etag=observed["bid_etag"]),
    )
    assert replay.status_code == 201 and replay.json() == ack
    assert replay.headers["idempotent-replayed"] == "true"
    assert w["io"]["calls"] == calls
    detail = w["client"].get("/api/v1/submissions/" + saved["id"])
    assert detail.status_code == 200 and detail.json() == saved
    validate_response(w, "/api/v1/submissions/{submission_id}", "get", detail)
    listing = w["client"].get(f"/api/v1/bids/{w['scope'].bid_id}/submissions")
    assert listing.status_code == 200 and listing.json()["items"] == [saved]
    validate_response(w, "/api/v1/bids/{bid_id}/submissions", "get", listing)
    assert not listing.json()["has_more"] and listing.json()["next_cursor"] is None
    changed = w["client"].post(
        base(w) + "/submissions",
        json=request | {"explanation": "A different fact with the old command key"},
        headers=headers(w, key=key, etag=observed["bid_etag"]),
    )
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert w["io"]["calls"] == calls


def test_http_preview_auth_scope_and_standard_gate_preserve_no_write_boundary(exact):
    w = exact
    anonymous = TestClient(w["app"])
    response = anonymous.post(base(w) + "/submission-preview", json=w["selection"])
    assert response.status_code in {401, 403}
    observed = preview(w)
    wrong = deepcopy(w["selection"])
    wrong["revision_id"] = uid()
    mismatched = w["client"].post(base(w) + "/submission-preview", json=wrong, headers=headers(w))
    assert mismatched.status_code == 422
    request = body(w, observed)
    standard = w["client"].post(
        base(w) + "/submissions",
        json=request | {"kind": "standard"},
        headers=headers(w, etag=observed["bid_etag"]),
    )
    assert standard.status_code == 409
    assert standard.json()["code"] == "PACKAGE_SUBMISSION_GATE_BLOCKED"
    assert w["io"]["calls"] == []
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM submission_records WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 0
        )


def test_shared_head_correction_keeps_old_package_and_blocks_single_body_downgrade(exact):
    w = exact
    _, _, _, first = register_http(w)
    original = first.json()["submission"]
    old = w["own"]["manifest"]
    newer = w["client"].post(
        f"{w['base']}/{old['package_id']}/revisions",
        json={"members": [w["item"]]},
        headers=headers(w, etag=etag("bid-package-head", old["package_id"], w["own"]["digest"])),
    )
    assert newer.status_code == 201, newer.text
    package = newer.json()
    selection = w["selection"] | {
        "revision_id": package["manifest"]["revision_id"],
        "package_digest": package["digest"],
    }
    observed = preview(w, selection)
    assert observed["current_submission_head"]["id"] == original["id"]
    request = body(w, observed, correction=True)
    corrected = w["client"].post(
        "/api/v1/submissions/" + original["id"] + "/package-corrections",
        json=request,
        headers=headers(w, etag=observed["bid_etag"]),
    )
    assert corrected.status_code == 201, corrected.text
    validate_response(
        w, "/api/v1/submissions/{submission_id}/package-corrections", "post", corrected
    )
    current = corrected.json()["submission"]
    assert current["supersedes_id"] == original["id"] and current["current"]
    assert (
        current["package_binding"]["manifest"]["subject"]["revision_id"] == selection["revision_id"]
    )
    history = w["client"].get("/api/v1/submissions/" + original["id"]).json()
    assert not history["current"] and history["package_binding"] == original["package_binding"]
    listing = w["client"].get(f"/api/v1/bids/{w['scope'].bid_id}/submissions", params={"limit": 1})
    assert listing.json()["items"][0]["id"] == current["id"] and listing.json()["has_more"]
    rest = w["client"].get(
        f"/api/v1/bids/{w['scope'].bid_id}/submissions",
        params={"cursor": listing.json()["next_cursor"], "limit": 1},
    )
    assert rest.json()["items"][0]["id"] == original["id"] and not rest.json()["has_more"]
    downgrade = w["client"].post(
        "/api/v1/submissions/" + current["id"] + "/corrections",
        json={
            "kind": "offline_fact",
            "submission": {
                "actual_document_version_id": w["member"].document_version_id,
                "evidence_ref": w["attachment"]["document_version_id"],
                "submitted_at": request["submitted_at"],
                "explanation": "Synthetic attempted body downgrade",
            },
            "reason": "Synthetic precise downgrade rejection",
        },
        headers=headers(w, etag=corrected.headers["x-bid-etag"]),
    )
    assert downgrade.status_code == 409, downgrade.text
    assert downgrade.json()["code"] == "PACKAGE_SUBMISSION_CORRECTION_REQUIRED"
    with connection() as c:
        head = c.execute(
            "SELECT * FROM submission_heads WHERE bid_id=%s", (w["scope"].bid_id,)
        ).fetchone()
        assert str(head["submission_id"]) == current["id"] and head["revision"] == 2


def test_shared_metrics_do_not_inherit_single_body_risk_prediction_or_backfill_history(
    exact, monkeypatch
):
    w = exact
    _, _, _, response = register_http(w)
    submission = response.json()["submission"]
    calls = []
    original = snapshots.current_risks

    def observed(*args, **kwargs):
        calls.append((args[1:], kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(snapshots, "current_risks", observed)
    result = metrics(w)
    assert not calls
    assert result["effective_submissions"] == 1 and result["unknown_outcomes"] == 1
    quality = result["qualification"]
    assert quality["known_current_review_submissions"] == 0
    assert quality["unknown_current_review_submissions"] == 1
    assert (
        quality["identified"]
        is quality["resolved"]
        is quality["dismissed"]
        is quality["open"]
        is None
    )
    assert quality["known_snapshot_submissions"] == 0
    assert quality["unknown_snapshot_submissions"] == 1
    assert result["online_error"]["prediction_pairs"] == 0
    assert result["online_error"]["excluded_pair_counts"] == {
        "package_prediction_producer_unavailable": 1
    }
    assert result["model_qualification_granted"] is False
    before = datetime.fromisoformat(submission["recorded_at"].replace("Z", "+00:00")) - timedelta(
        seconds=1
    )
    historical = metrics(w, as_of=before.isoformat())
    assert historical["effective_submissions"] == 0
    assert historical["scope"]["excluded_submission_counts"]["not_observed_at_as_of"] == 1
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM audit_entries WHERE bid_id=%s AND event_type=ANY(%s)",
                (w["scope"].bid_id, [records.RISK, records.PAIR]),
            ).fetchone()["n"]
            == 0
        )


def test_official_package_http_verification_business_result_and_withdrawal_recheck(exact):
    w = outcome_case(exact)
    result_id = w["result"]["id"]
    verified = w["client"].post(
        "/api/v1/outcomes/" + result_id + "/verification",
        json=w["verification"],
        headers=headers(w, etag=w["result_headers"]["verification-etag"]),
    )
    assert verified.status_code == 200, verified.text
    validate_response(w, "/api/v1/outcomes/{outcome_id}/verification", "post", verified)
    original_details = verified.json()["verification_details"]
    available = w["client"].get("/api/v1/outcomes/" + result_id)
    assert available.status_code == 200, available.text
    validate_response(w, "/api/v1/outcomes/{outcome_id}", "get", available)
    association = available.json()["package_association"]
    assert association["available"] and association["reasons"] == []
    assert association["scope"] == "official_outcome_association"
    assert association["formal_sample_eligible"] is False
    assert datetime.fromisoformat(association["checked_at"].replace("Z", "+00:00")).tzinfo
    with connection() as c:
        native = c.execute("SELECT * FROM outcomes WHERE id=%s", (result_id,)).fetchone()
        assert sources.outcome_reasons(c, native, datetime.now(timezone.utc)) == []
    submission = w["submission"]["id"]
    base = f"/api/v1/bids/{w['scope'].bid_id}/submissions/{submission}/business-results"
    page = w["client"].get(base)
    assert page.status_code == 200 and page.json()["current_result"] is None
    business = {
        "submission_id": submission,
        "stage": "technical_shortlisted",
        "source_type": "official",
        "source_version_id": w["source"],
        "evidence_refs": w["verification"]["evidence_refs"],
        "announced_at": w["result_request"]["known_at"],
        "known_at": w["result_request"]["known_at"],
        "reason": "Synthetic explicit business-stage observation, not inferred from the technical score",
    }
    registered = w["client"].post(
        base, json=business, headers=headers(w, etag=page.headers["etag"])
    )
    assert registered.status_code == 201, registered.text
    verify_body = {
        "state": "verified",
        "reason": "Synthetic source and original identity association checked",
        "identity_confirmed": True,
        "evidence_refs": business["evidence_refs"],
    }
    key = uid()
    checked = w["client"].post(
        "/api/v1/business-results/" + registered.json()["id"] + "/verification-decisions",
        json=verify_body,
        headers=headers(w, key=key, etag=registered.headers["etag"]),
    )
    assert checked.status_code == 200 and checked.json()["usable"], checked.text
    validate_response(
        w, "/api/v1/business-results/{result_id}/verification-decisions", "post", checked
    )
    summary = metrics(w, verification_scope="verified_only")
    assert summary["effective_submissions"] == summary["known_outcomes"] == 1
    assert summary["stage_counts"]["technical_shortlisted"] == 1
    assert summary["online_error"]["prediction_pairs"] == 0
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (original_source_id(UUID(w["source"])),),
        )
    reread = w["client"].get("/api/v1/business-results/" + registered.json()["id"])
    assert reread.status_code == 200 and reread.json()["verification"] == "verified"
    assert (
        not reread.json()["usable"]
        and "source_no_longer_effective" in reread.json()["unusable_reasons"]
    )
    replay = w["client"].post(
        "/api/v1/business-results/" + registered.json()["id"] + "/verification-decisions",
        json=verify_body,
        headers=headers(w, key=key, etag=registered.headers["etag"]),
    )
    assert replay.status_code == 200 and replay.headers["idempotent-replayed"] == "true"
    assert not replay.json()["usable"]
    after = metrics(w, verification_scope="verified_only")
    assert after["known_outcomes"] == 0 and after["unusable_outcomes"] == 1
    with connection() as c:
        native = c.execute("SELECT * FROM outcomes WHERE id=%s", (result_id,)).fetchone()
        assert sources.outcome_reasons(c, native, datetime.now(timezone.utc))
    historical_response = w["client"].get("/api/v1/outcomes/" + result_id)
    assert historical_response.status_code == 200, historical_response.text
    validate_response(w, "/api/v1/outcomes/{outcome_id}", "get", historical_response)
    historical = historical_response.json()
    assert (
        historical["verification_details"] == original_details
        and historical["verification"] == "verified"
    )
    assert not historical["package_association"]["available"]
    assert historical["package_association"]["reasons"]
    assert historical["package_association"]["formal_sample_eligible"] is False
