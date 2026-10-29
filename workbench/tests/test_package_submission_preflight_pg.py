"""Native nonowner PG/ASGI preflight; synthetic object bytes, no paid model calls."""
# ruff: noqa: F401,F811

import json
import os
import time
from copy import deepcopy
from pathlib import Path

import psycopg
import pytest
from test_bid_package_submissions_pg import (
    _RunCases,
    api,
    catalog,
    counts,
    database,
    exact,
    headers,
    inventory,
    preview,
    request,
    requirements,
    uid,
    world,
)

from apps.api.views import bid_etag
from packages.contracts.package_submissions_api import valid
from packages.domain import package_submission_preflight as preflight
from packages.domain.runtime import DomainError, connection

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner submission preflight PG17 required",
)


def verify(w, p, *, final_auth=None):
    return preflight.inspect(
        w["submission_scope"],
        w["actor"],
        {"selection": p["selection_request"], "input_digest": p["input_digest"]},
        p["bid_etag"],
        bid_etag_fn=bid_etag,
        final_auth=final_auth or (lambda: w["actor"]),
    )


def test_native_api_checks_originals_without_command_fact_task_or_original_locator(exact):
    p = preview(exact)
    before = counts(exact)
    path = "/api/v1/bids/{}/packages/{}/revisions/{}/submission-preflight".format(
        *exact["submission_scope"]
    )
    response = exact["client"].post(
        path,
        json={"selection": p["selection_request"], "input_digest": p["input_digest"]},
        headers=headers(exact, etag=p["bid_etag"]),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert valid("PackageSubmissionPreflightView", result)
    assert response.headers["cache-control"].replace(" ", "") == "private,no-store"
    m = result["manifest"]
    assert m["actor_id"] == exact["actor"] and m["input_digest"] == p["input_digest"]
    assert m["subject"]["package_digest"] == exact["own"]["digest"]
    assert m["gates"]["current_input"]["original_verification"] == "verified_at_observation"
    assert m["review_runtime"]["state"] == "not_selected"
    assert m["submission_eligible"] is m["allowed"] is False
    assert len(exact["io"]["calls"]) == len(m["originals"]) == 1
    assert counts(exact) == before == (0, 0, 0)
    assert preview(exact)["input_digest"] == p["input_digest"]
    assert "object_key" not in response.text and "blob_id" not in response.text


def test_native_exact_authority_and_target_originals_are_both_verified(exact):
    response = inventory(exact)
    assert response.status_code == 201, response.text
    inv = response.json()
    p = preview(
        exact,
        exact["selection"] | {"inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]}},
    )
    result = verify(exact, p)["manifest"]
    assert len(exact["io"]["calls"]) == len(result["originals"]) == 2
    assert {role for row in result["originals"] for role in row["roles"]} >= {"target", "authority"}
    assert result["gates"]["core_coverage"]["inventory_complete"] is False
    assert counts(exact) == (0, 0, 0)


@pytest.mark.parametrize("change", ["bytes", "unavailable", "source", "head", "session", "actor"])
def test_native_changes_and_auth_loss_during_original_reads_produce_no_receipt(exact, change):
    p = preview(exact)
    auth = None
    if change == "bytes":
        exact["io"]["corrupt"] = True
    elif change == "unavailable":
        exact["io"]["unavailable"] = True
    elif change == "session":

        def auth():
            raise DomainError("AUTHENTICATION_REQUIRED", "synthetic expired session", 401)
    elif change == "actor":
        auth = uid
    else:

        def callback():
            with connection() as c:
                if change == "source":
                    c.execute(
                        "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                        (exact["sources"][0],),
                    )
                elif change == "head":
                    c.execute(
                        "UPDATE design.bids SET revision=revision+1 WHERE id=%s",
                        (exact["scope"].bid_id,),
                    )

        exact["io"]["callback"] = callback
    with pytest.raises(DomainError) as failure:
        verify(exact, p, final_auth=auth)
    assert failure.value.status in {401, 403, 409, 412, 503}
    assert counts(exact) == (0, 0, 0)


def test_native_etag_and_input_digest_are_required_before_any_object_read(exact):
    p = preview(exact)
    for bad in (p | {"bid_etag": '"wrong"'}, p | {"input_digest": "0" * 64}):
        with pytest.raises(DomainError):
            verify(exact, bad)
    assert not exact["io"]["calls"] and counts(exact) == (0, 0, 0)


def test_native_original_locator_is_immutable_and_cannot_change_under_a_receipt(exact):
    p = preview(exact)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable_record"):
        with connection() as c:
            c.execute(
                "UPDATE design.blobs SET object_key=object_key||'-moved' WHERE id=(SELECT blob_id FROM design.document_versions WHERE id=%s)",
                (exact["member"].document_version_id,),
            )
    result = verify(exact, p)
    assert result["manifest"]["input_digest"] == p["input_digest"]
    assert counts(exact) == (0, 0, 0)


def test_source_expiry_during_object_io_is_detected_without_row_or_etag_change(exact):
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,valid_until=clock_timestamp()+interval '3 seconds' WHERE source_id=%s",
            (exact["sources"][0],),
        )
    p = preview(exact)
    assert (
        "PACKAGE_SOURCE_NOT_EFFECTIVE"
        not in p["gate"]["manifest"]["gates"]["current_input"]["codes"]
    )

    def expires():
        with connection() as c:
            delay = c.execute(
                "SELECT greatest(0,extract(epoch FROM valid_until-clock_timestamp())) AS seconds FROM retrieval.source_heads WHERE source_id=%s",
                (exact["sources"][0],),
            ).fetchone()["seconds"]
        assert float(delay) <= 3
        time.sleep(float(delay) + 0.02)

    exact["io"]["callback"] = expires
    with pytest.raises(DomainError) as failure:
        verify(exact, p)
    assert failure.value.code == "PACKAGE_SUBMISSION_PREFLIGHT_CONTEXT_CHANGED"
    with connection() as c:
        assert bid_etag(c, exact["scope"].bid_id) == p["bid_etag"]
    assert counts(exact) == (0, 0, 0)


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestExactReviewRuntime:
    original_case = _RunCases.original_case
    frozen_case = _RunCases.frozen_case
    execution_case = _RunCases.execution_case
    prepared_case = _RunCases.prepared_case
    exact_inventory_proof_case = _RunCases.exact_inventory_proof_case
    launch_case = _RunCases.launch_case
    post = _RunCases.post
    launch = _RunCases.launch
    message = _RunCases.message
    provider = _RunCases.provider

    def test_current_native_review_dependencies_are_rebuilt_without_new_provider_calls(
        self, launch_case, monkeypatch
    ):
        from apps.worker import engine

        case = launch_case
        paid = self.provider(case, monkeypatch)
        launched = self.launch(case)
        assert launched.status_code == 202, launched.text
        run = launched.json()
        engine.handle_lane("review", self.message(case, run))
        actual = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert actual.status_code == 200, actual.text
        run = actual.json()
        assert run["operation"]["state"] == "succeeded" and len(paid) == 1
        inv = case["w"]["client"].get(case["w"]["requirement_base"] + "/" + case["scope"][3]).json()
        w = case["w"] | {
            "submission_scope": case["scope"][:3],
            "selection": {
                "package_id": case["scope"][1],
                "revision_id": case["scope"][2],
                "package_digest": case["w"]["own"]["digest"],
                "inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]},
                "coverage": None,
                "review_run": {
                    "id": run["id"],
                    "input_digest": run["input_digest"],
                    "result_digest": run["result"]["digest"],
                },
            },
        }
        p = preview(w)
        result = verify(w, p)
        assert valid("PackageSubmissionPreflightView", result)
        m = result["manifest"]
        assert m["review_runtime"]["state"] == "matched"
        assert m["review_runtime"]["current_input_digest"] == run["input_digest"]
        assert m["gates"]["current_input"]["state"] == "pass"
        assert m["gates"]["core_coverage"]["state"] == "unknown"
        assert m["allowed"] is m["inventory_complete"] is m["submission_eligible"] is False
        assert len(paid) == 1 and counts(w) == (0, 0, 0)
        target = Path("/tmp/tender-completion-runtime/submission-preflight")
        target.mkdir(parents=True, exist_ok=True)
        for name, item in {"preview": p, "preflight": result}.items():
            (target / (name + ".json")).write_text(json.dumps(item, ensure_ascii=False, indent=2))
        # A native source withdrawal invalidates the original execution basis;
        # no extra provider request can turn the historical result into current.
        with connection() as c:
            c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (w["sources"][0],),
            )
        changed = verify(w, preview(w))["manifest"]
        assert changed["review_runtime"]["state"] == "blocked"
        assert changed["gates"]["current_input"]["state"] == "blocked"
        assert len(paid) == 1
