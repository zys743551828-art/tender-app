"""Exact eligibility UI catalogue: real API shapes with explicitly synthetic material."""
# ruff: noqa: F401,F811

import json
import os
from pathlib import Path

from test_package_technical_eligibility_pg import (
    api,
    database,
    exact,
    frozen,
    inventory,
    outcome_case,
    pytestmark,
    requirements,
    submission_world,
    verify,
    world,
)


def test_native_catalogue_and_selected_context_keep_the_same_exact_submission(exact, monkeypatch):
    saved, path = frozen(exact)
    w = outcome_case(submission_world(exact, monkeypatch), with_authority=False)
    verify(w)
    client = w["client"]
    bid = saved["manifest"]["preview"]["manifest"]["scope"]["bid_id"]
    params = {"submission_id": w["submission"]["id"], "outcome_id": w["result"]["id"]}
    sample = client.get(path + "/sample-context", params=params)
    current = client.get(path + "/scoring-context")
    submissions = client.get(f"/api/v1/bids/{bid}/submissions?limit=20")
    outcomes = client.get(f"/api/v1/bids/{bid}/outcomes")
    capabilities = client.get("/api/v1/technical-scale-capabilities")
    for response in (sample, current, submissions, outcomes, capabilities):
        assert response.status_code == 200, response.text
    assert not capabilities.json()["schema_configured"]
    assert submissions.json()["items"][0]["id"] == params["submission_id"]
    assert outcomes.json()["items"][0]["id"] == params["outcome_id"]
    assert (
        sample.json()["submission"]["binding_digest"]
        == submissions.json()["items"][0]["package_binding"]["digest"]
    )
    assert sample.json()["official_result"]["technical_value"] == "0"
    assert sample.json()["sample_created"] is False
    assert "official_result" not in current.json()
    destination = os.environ.get("FUSION_TECHNICAL_CATALOG_FIXTURE")
    if destination:
        Path(destination).write_text(
            json.dumps(
                {
                    "schema": "package-technical-eligibility-catalogue-http-fixture/1",
                    "evidence": "Actual PG17 nonowner ASGI catalogue and selected contexts; synthetic original materials; no model calls",
                    "scope": saved,
                    "basePath": path,
                    "sampleRequest": params,
                    "sampleContext": sample.json(),
                    "sampleEtag": sample.headers["etag"],
                    "scoringContext": current.json(),
                    "scoringEtag": current.headers["etag"],
                    "submissions": submissions.json(),
                    "outcomes": outcomes.json(),
                    "capabilities": capabilities.json(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
