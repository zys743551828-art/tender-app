"""Strict human intent and immutable change receipt; no database authority in these tests."""

from copy import deepcopy

import pytest

from packages.domain import package_fact_changes as policy
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from tests.test_package_fact_scope import uid


@pytest.fixture
def request_body():
    return dict(
        frozen_digest="a" * 64,
        expected_head=dict(id=None, revision=0),
        replaces_fact_id=None,
        confirmation="confirmed",
        fact=dict(
            subject="本工程",
            scope="本标段",
            name="工期",
            value="180",
            unit="天",
            evidence_ids=[uid(10)],
            reason="按明确原页确认",
        ),
    )


@pytest.fixture
def manifest():
    return dict(
        version="package-fact-change/1",
        kind="package_fact_change",
        command_id=uid(1),
        actor_id=uid(2),
        action="confirmed",
        recorded_at="2026-10-20T00:00:00.000000Z",
        reason="按明确原页确认",
        binding=dict(
            zip(
                ("bid_id", "package_id", "revision_id", "inventory_id", "frozen_input_id"),
                [uid(n) for n in range(3, 8)],
                strict=True,
            )
        )
        | dict(frozen_digest="a" * 64),
        previous_head=dict(id=None, revision=0),
        head=dict(id=uid(8), revision=1),
        fact_id=uid(9),
        replaces_fact_id=None,
        decision_id=uid(11),
        evidence_selection_digest="b" * 64,
        evidence_basis_digest="c" * 64,
        original_bytes_verified=False,
        facts_qualified=False,
        review_ready=False,
        launch_available=False,
        publication_authorized=False,
    )


def test_confirm_intent_and_receipt_are_owned_without_review_authority(request_body, manifest):
    policy.validate("ConfirmRequest", request_body)
    value = policy.seal(manifest)
    copy = policy.verify(value)
    copy["manifest"]["head"]["id"] = uid(999)
    assert value["manifest"]["head"]["id"] == uid(8)
    manifest["reason"] = "changed"
    assert value["manifest"]["reason"] == "按明确原页确认"


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "no_confirmation",
        "wrong_confirmation",
        "duplicate_evidence",
        "empty_evidence",
        "number_value",
        "empty_name",
        "space_reason",
        "long_reason",
        "bool_revision",
        "unknown_head",
        "injected_reader",
    ],
)
def test_incomplete_or_injected_human_intent_is_rejected(request_body, change):
    if change == "extra":
        request_body["launch_available"] = True
    if change == "no_confirmation":
        del request_body["confirmation"]
    if change == "wrong_confirmation":
        request_body["confirmation"] = "automatic"
    if change == "duplicate_evidence":
        request_body["fact"]["evidence_ids"] *= 2
    if change == "empty_evidence":
        request_body["fact"]["evidence_ids"] = []
    if change == "number_value":
        request_body["fact"]["value"] = 180
    if change == "empty_name":
        request_body["fact"]["name"] = " "
    if change == "space_reason":
        request_body["fact"]["reason"] = " reason "
    if change == "long_reason":
        request_body["fact"]["reason"] = "x" * 2001
    if change == "bool_revision":
        request_body["expected_head"]["revision"] = True
    if change == "unknown_head":
        request_body["expected_head"]["other"] = None
    if change == "injected_reader":
        request_body["evidence_reader"] = "trusted"
    with pytest.raises(DomainError):
        policy.validate("ConfirmRequest", request_body)


@pytest.mark.parametrize(
    "change",
    [
        "head_revision",
        "same_head",
        "missing_previous_id",
        "missing_decision",
        "missing_evidence",
        "authority",
        "same_fact_replacement",
        "initial_replacement",
        "withdrawal_proof",
        "initial_withdrawal",
        "reason",
    ],
)
def test_resealed_inconsistent_receipt_cannot_be_consumed(manifest, change):
    m = deepcopy(manifest)
    if change == "head_revision":
        m["head"]["revision"] = 2
    if change == "same_head":
        m["previous_head"] = dict(m["head"])
        m["head"]["revision"] += 1
    if change == "missing_previous_id":
        m["previous_head"]["revision"] = 1
        m["head"]["revision"] = 2
    if change == "missing_decision":
        m["decision_id"] = None
    if change == "missing_evidence":
        m["evidence_basis_digest"] = None
    if change == "authority":
        m["facts_qualified"] = True
    if change == "same_fact_replacement":
        m["replaces_fact_id"] = m["fact_id"]
        m["previous_head"] = dict(id=uid(12), revision=1)
        m["head"]["revision"] = 2
    if change == "initial_replacement":
        m["replaces_fact_id"] = uid(12)
    if change == "withdrawal_proof":
        m["action"] = "withdrawn"
    if change == "initial_withdrawal":
        m.update(
            action="withdrawn",
            decision_id=None,
            evidence_selection_digest=None,
            evidence_basis_digest=None,
        )
    if change == "reason":
        m["reason"] = " reason "
    with pytest.raises(DomainError) as error:
        policy.verify(dict(manifest=m, digest=digest(m)))
    assert error.value.code == "PACKAGE_FACT_CHANGE_CORRUPT"


def test_withdrawal_receipt_never_claims_a_new_confirmation(manifest):
    manifest.update(
        action="withdrawn",
        previous_head=dict(id=uid(12), revision=1),
        head=dict(id=uid(13), revision=2),
        decision_id=None,
        evidence_selection_digest=None,
        evidence_basis_digest=None,
    )
    assert policy.verify(policy.seal(manifest))["manifest"]["decision_id"] is None
