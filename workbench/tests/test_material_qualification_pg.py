"""Opt-in isolated PG17 review lifecycle; no model/account/budget writes."""

# ruff: noqa: F401,F811
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from test_material_qualification import document
from test_package_technical_eligibility_pg import frozen
from test_package_technical_execution_pg import api
from test_package_technical_scope_pg import database, exact, headers, requirements, world

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_TECHNICAL_SCOPE_PG") != "1",
    reason="explicit isolated PG17 technical-scope fixture required",
)


def test_native_review_lifecycle(exact, database):
    owner = database["owner"]
    owner.execute(
        (Path(__file__).resolve().parents[1] / "deploy/sql/material-qualification.sql").read_text()
    )
    saved, base = frozen(exact)
    path = base + "/material-qualifications"
    body = document()
    body["binding"]["scope_digest"] = saved["digest"]
    bid = saved["manifest"]["preview"]["manifest"]["scope"]["bid_id"]
    proof = owner.execute(
        "SELECT v.id,b.digest FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s LIMIT 1",
        (bid,),
    ).fetchone()
    for item in body["evidence"].values():
        item.update(document_version_id=str(proof["id"]), digest=proof["digest"])
    now = datetime.now(timezone.utc)
    start, end = (now - timedelta(minutes=1)).isoformat(), (now + timedelta(hours=1)).isoformat()
    body.update(valid_from=start, valid_until=end)
    body["price"].update(source_observed_at=start, valid_from=start, valid_until=end)
    h = headers(exact)
    response = exact["client"].post(path, json=body, headers=h)
    assert response.status_code == 201, response.text
    original = response.json()
    assert not original["execution_authorized"] and not original["accuracy_verified"]
    assert exact["client"].post(path, json=body, headers=h).json() == original
    read_path = path + "/" + original["id"]
    decision_path = read_path + "/decisions"
    approved = {"decision": "approved", "reason": "Synthetic evidence reviewed"}
    dh = headers(exact, etag=response.headers["etag"])
    result = exact["client"].post(decision_path, json=approved, headers=dh)
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "approved"
    assert exact["client"].post(decision_path, json=approved, headers=dh).json() == result.json()
    revoked_body = {"decision": "revoked", "reason": "Withdraw"}
    assert (
        exact["client"]
        .post(
            decision_path, json=revoked_body, headers=headers(exact, etag=response.headers["etag"])
        )
        .status_code
        == 412
    )
    revoked = exact["client"].post(
        decision_path, json=revoked_body, headers=headers(exact, etag=result.headers["etag"])
    )
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert (
        exact["client"]
        .post(decision_path, json=approved, headers=headers(exact, etag=revoked.headers["etag"]))
        .status_code
        == 409
    )
    assert exact["client"].post(decision_path, json=approved, headers={}).status_code in (401, 403)
    wrong = read_path.replace(saved["manifest"]["id"], str(uuid4()))
    assert exact["client"].get(wrong).status_code == 404
