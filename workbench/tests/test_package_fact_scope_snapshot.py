"""Actual saved proof must survive later changes without inventing historical state."""

import json
from copy import deepcopy

import pytest

from packages.domain.package_fact_scope_snapshot import consume, freeze
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha
from tests.test_package_fact_scope import case, declare, uid  # noqa: F401


@pytest.fixture
def saved(case):  # noqa: F811
    record = declare(case)
    proof = deepcopy(case["proof"])
    proof.update(version="package-fact-provenance/2", decision_lineage=[])
    proof["references"] = [
        dict(source_id=uid(33), source_revision=1, evidence_id=uid(32), document_version_id=uid(35))
    ]
    proof["closure"] = [
        dict(
            source_id=uid(33),
            id=uid(33),
            document_version_id=uid(35),
            kind="parse",
            policy_class="prebid_content",
            known_at="2026-10-19T00:00:00+00:00",
            digest="a" * 64,
            revision=1,
            status="published",
            valid_from="2026-10-19T00:00:00+00:00",
            valid_until="2026-10-21T00:00:00+00:00",
        )
    ]
    record["manifest"]["binding"]["proof_digest"] = digest(proof)
    record["digest"] = digest(record["manifest"])
    text = freeze(proof, case["audit"]["recorded_at"])
    return record | dict(proof_text=text, proof_snapshot_digest=sha(text.encode()))


def test_saved_literal_proof_is_private_defensive_and_not_current_state(saved):
    packet = consume(saved)
    assert packet.snapshot_text() == saved["proof_text"]
    assert packet.view() == {k: saved[k] for k in ("manifest", "digest")}
    changed = packet.proof()
    changed["closure"][0]["status"] = "withdrawn"
    assert packet.proof()["closure"][0]["status"] == "published"
    assert "proof_text" not in repr(packet) and "parse" not in repr(packet)


@pytest.mark.parametrize(
    "change", ["bytes", "hash", "proof", "time", "unknown", "duplicate", "expired"]
)
def test_corrupt_saved_proof_fails_even_if_outer_bytes_are_resealed(saved, change):
    value = json.loads(saved["proof_text"])
    if change == "proof":
        value["proof"]["closure"][0]["revision"] = 2
    if change == "time":
        value["observed_at"] = "2026-10-20T01:00:00.000000Z"
    if change == "unknown":
        value["inferred_history"] = True
    if change == "expired":
        value["proof"]["closure"][0]["valid_until"] = "2026-10-19T12:00:00+00:00"
    text = json.dumps(value)
    if change == "duplicate":
        text = text.replace('"version":', '"version":"forged","version":', 1)
    saved["proof_text"] = text
    saved["proof_snapshot_digest"] = sha(text.encode())
    if change == "bytes":
        saved["proof_text"] += " "
    if change == "hash":
        saved["proof_snapshot_digest"] = "0" * 64
    with pytest.raises(DomainError) as error:
        consume(saved)
    assert error.value.code == "PACKAGE_FACT_SCOPE_CORRUPT"
