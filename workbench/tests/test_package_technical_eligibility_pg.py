"""Actual BASE-only PG/API contexts with synthetic originals and official result.

The test intentionally leaves the optional denominator authority uninstalled.
No synthetic model, paid provider, formal score or research sample is produced.
"""
# ruff: noqa: F401,F811

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from test_bid_package_submissions_pg import exact as submission_case
from test_bid_package_submissions_pg import register, request
from test_package_outcomes_pg import setup as outcome_case
from test_package_outcomes_pg import verify
from test_package_technical_scope_pg import (
    RAW,
    database,
    exact,
    freeze,
    headers,
    inventory,
    requirements,
    uid,
    world,
)
from test_package_technical_scope_pg import (
    api as scope_api,
)

from apps.api.package_technical_eligibility import router
from packages.contracts import package_technical_eligibility_api as contracts
from packages.domain.runtime import connection, sha
from packages.rag.indexing import original_source_id

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_TECHNICAL_SCOPE_PG") != "1",
    reason="separate explicit F06 BASE-only PostgreSQL required",
)


@pytest.fixture
def api(database):
    source = scope_api.__wrapped__(database)
    value = next(source)
    app = value["app"]
    if not any(
        getattr(route, "path", "").endswith("/technical-scopes/{scope_id}/scoring-context")
        for route in app.router.routes
    ):
        app.include_router(router)
    app.openapi_schema = None
    try:
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def frozen(w):
    result, replay = freeze(w)
    assert not replay
    saved = result["body"]["scope"]
    return saved, w["technical_base"] + "/technical-scopes/" + saved["manifest"]["id"]


def counts(w):
    with connection() as c:
        return {
            table: c.execute(
                f"SELECT count(*) AS n FROM design.{table} WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            for table in ("operations", "samples", "bid_package_technical_scopes")
        }


def codes(value):
    return {row["code"] for row in value["blockers"]}


def test_native_scoring_context_does_not_require_optional_authorities_or_write_jobs(exact):
    w = exact
    saved, path = frozen(w)
    before, reads = counts(w), list(w["io"]["reads"])
    result = w["client"].get(path + "/scoring-context")
    assert result.status_code == 200, result.text
    value = result.json()
    contracts.validate("PackageTechnicalScoringContext", value)
    assert value["current_input"]["state"] == "matched"
    assert value["denominator"]["state"] == "unselected"
    assert value["numeric_prediction"] is None and value["training_eligible"] is False
    assert value["official_label_access"] == "forbidden"
    again = w["client"].get(path + "/scoring-context")
    assert again.headers["etag"] == result.headers["etag"]
    missing = w["client"].get(path + "/scoring-context", params={"scale_id": uid()})
    assert missing.status_code == 200, missing.text
    assert missing.json()["denominator"]["state"] == "not_configured"
    assert missing.json()["denominator"]["technical_maximum"] is None
    assert counts(w) == before and w["io"]["reads"] == reads
    assert w["client"].get(path).json() == saved
    assert (
        "private" in result.headers["cache-control"]
        and "no-store" in result.headers["cache-control"]
    )


def test_native_current_source_withdrawal_does_not_rewrite_original_scope(exact):
    w = exact
    saved, path = frozen(w)
    first = w["client"].get(path + "/scoring-context")
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(w["member"].document_version_id)),),
        )
    result = w["client"].get(path + "/scoring-context")
    assert result.status_code == 200, result.text
    assert result.json()["current_input"]["state"] == "changed"
    assert "SOURCE_UNAVAILABLE" in codes(result.json())
    assert first.headers["etag"] != result.headers["etag"]
    assert w["client"].get(path).json() == saved
    wrong = w["client"].get(path.replace(saved["manifest"]["id"], uid()) + "/scoring-context")
    assert wrong.status_code == 404


def submission_world(w, monkeypatch):
    submission = submission_case.__wrapped__(w, monkeypatch)
    # Same real synthetic object bytes that the scope already verified; do not
    # substitute the other suite's fixture body with a different digest.
    submission["io"]["data"][sha(RAW)] = RAW
    submission["selection"]["inventory"] = {
        "id": w["inventory"]["manifest"]["id"],
        "digest": w["inventory"]["digest"],
    }
    return submission


def test_native_exact_submission_verified_zero_still_stays_pending_and_rechecks_sources(
    exact, monkeypatch
):
    saved, path = frozen(exact)
    w = outcome_case(submission_world(exact, monkeypatch), with_authority=False)
    with connection() as c:
        identity = c.execute(
            "SELECT design.identity_snapshot_v2(%s) AS value", (w["scope"].bid_id,)
        ).fetchone()["value"]
        assert identity["binding_status"] == "confirmed"
    verify(w)
    params = {"submission_id": w["submission"]["id"], "outcome_id": w["result"]["id"]}
    before, calls = counts(w), list(w["io"]["calls"])
    result = w["client"].get(path + "/sample-context", params=params)
    assert result.status_code == 200, result.text
    value = result.json()
    contracts.validate("PackageTechnicalSampleContext", value)
    assert value["submission"]["matches_scope"] and value["submission"]["is_current_head"]
    assert value["original_scope_precedes_submission"] and value["source_metadata_matches"]
    assert value["official_result"]["current_association"]
    assert float(value["official_result"]["technical_value"]) == 0
    assert value["denominator"]["technical_maximum"] is None
    assert (
        value["timing"]["training_frozen_at"] is None and not value["timing"]["strict_timing_ready"]
    )
    assert value["sample_state"] == "pending" and value["sample_created"] is False
    assert counts(w) == before and w["io"]["calls"] == calls
    current = w["client"].get(path + "/scoring-context")
    assert current.status_code == 200 and "AFTER_SUBMISSION" in codes(current.json())
    assert current.json()["official_label_access"] == "forbidden"
    assert "official_result" not in current.json()
    destination = os.environ.get("FUSION_TECHNICAL_ELIGIBILITY_FIXTURE")
    if destination:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema": "package-technical-eligibility-http-fixture/1",
                    "evidence": "Actual BASE-only PG and ASGI API; synthetic originals and official zero; no model/sample qualification",
                    "basePath": path,
                    "scope": saved,
                    "sampleRequest": params,
                    "sampleContext": value,
                    "sampleEtag": result.headers["etag"],
                    "scoringContext": current.json(),
                    "scoringEtag": current.headers["etag"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(w["source"])),),
        )
    changed = w["client"].get(path + "/sample-context", params=params)
    assert changed.status_code == 200, changed.text
    assert not changed.json()["official_result"]["current_association"]
    assert changed.headers["etag"] != result.headers["etag"]
    assert w["client"].get(path).json() == saved
    assert counts(w) == before
    wrong = w["client"].get(path + "/sample-context", params=params | {"outcome_id": uid()})
    assert wrong.status_code == 404


def test_native_late_offline_fact_cannot_backdate_scope_or_invent_missing_label(exact, monkeypatch):
    _, path = frozen(exact)
    w = submission_world(exact, monkeypatch)
    preview, body = request(w)
    # The fixture's actual submission is deliberately five minutes before this
    # freshly recorded scope. That is a truthful late-recorded fact, not proof.
    assert datetime.fromisoformat(body["submitted_at"]) < datetime.now(timezone.utc)
    ack, _ = register(w, body, preview["bid_etag"])
    result = w["client"].get(
        path + "/sample-context", params={"submission_id": ack["body"]["submission"]["id"]}
    )
    assert result.status_code == 200, result.text
    value = result.json()
    assert not value["original_scope_precedes_submission"]
    assert "SAMPLE_SCOPE_FROZEN_AFTER_SUBMISSION" in codes(value)
    assert value["official_result"]["technical_value"] is None
    assert value["sample_state"] == "pending" and value["sample_created"] is False
