"""Exact decimal scores remain readable and their successful command ACKs recoverable."""
# ruff: noqa: F401,F811

import os
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_bid_package_submissions_pg import (
    api,
    catalog,
    database,
    exact,
    headers,
    requirements,
    uid,
    world,
)
from test_package_outcomes_pg import setup
from test_stable_lot_identity import validate_response

from packages.domain.runtime import connection
from packages.research.outcomes import outcome_view


@pytest.mark.parametrize(
    ("value", "maximum"),
    [
        (None, None),
        ("0", "60"),
        ("0.0000000", "60.0000000"),
        ("0.0000001", "0.0000010"),
        ("12.3400", "100.0000"),
        ("0." + "0" * 90 + "1", "60"),
    ],
)
def test_native_decimal_projection_preserves_unknown_zero_scale_and_tiny_values(value, maximum):
    native = {
        "id": uid(),
        "bid_id": uid(),
        "submission_id": uid(),
        "score_kind": "technical_total",
        "value": Decimal(value) if value is not None else None,
        "maximum": Decimal(maximum) if maximum is not None else None,
        "source_version_id": uid(),
        "known_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "supersedes_id": None,
    }
    c = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: None))
    public = outcome_view(c, native)
    assert public["value"] == value and public["maximum"] == maximum
    assert native["value"] == (Decimal(value) if value is not None else None)
    assert public["verification"] == "pending" and public["verification_revision"] == 0


@pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner PostgreSQL required for exact native decimal ACK",
)
def test_actual_http_decimal_zero_tiny_score_and_exact_replay(exact):
    w = setup(exact)
    base_id, base_etag = w["result"]["id"], w["result_headers"]["etag"]
    expected = {base_id: "0"}
    for value in ("0.0000000", "0.0000001"):
        body = w["result_request"] | {"value": value, "maximum": "60.0000000"}
        key = uid()
        endpoint = "/api/v1/outcomes/" + base_id + "/corrections"
        sent_headers = headers(w, key=key, etag=base_etag)
        saved = w["client"].post(endpoint, json=body, headers=sent_headers)
        assert saved.status_code == 201, saved.text
        validate_response(w, "/api/v1/outcomes/{outcome_id}/corrections", "post", saved)
        ack = saved.json()
        assert ack["value"] == value and ack["maximum"] == body["maximum"]
        replay = w["client"].post(endpoint, json=body, headers=sent_headers)
        assert replay.status_code == 201 and replay.json() == ack
        assert replay.headers["idempotent-replayed"] == "true"
        assert replay.headers["etag"] == saved.headers["etag"]
        read = w["client"].get("/api/v1/outcomes/" + ack["id"])
        assert read.status_code == 200, read.text
        validate_response(w, "/api/v1/outcomes/{outcome_id}", "get", read)
        assert read.json()["value"] == value and read.json()["maximum"] == body["maximum"]
        with connection() as c:
            native = c.execute(
                "SELECT value,maximum FROM outcomes WHERE id=%s", (ack["id"],)
            ).fetchone()
            assert native["value"] == Decimal(value)
            assert native["value"].as_tuple().exponent == -7
            assert native["maximum"] == Decimal(body["maximum"])
        expected[ack["id"]] = value
        base_id, base_etag = ack["id"], saved.headers["etag"]
    page = w["client"].get(f"/api/v1/bids/{w['scope'].bid_id}/outcomes")
    assert page.status_code == 200, page.text
    validate_response(w, "/api/v1/bids/{bid_id}/outcomes", "get", page)
    assert {row["id"]: row["value"] for row in page.json()["items"]} == expected
