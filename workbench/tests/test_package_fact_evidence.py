"""Explicit frozen evidence selection; no current parse, fact qualification or IO."""

import json
from copy import deepcopy

import pytest

from packages.domain import package_fact_evidence as policy
from packages.domain.package_review_frozen_input import FrozenPackageReviewInput
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from tests.test_package_fact_scope import uid


@pytest.fixture
def packet():
    m = {
        key: uid(n)
        for n, key in enumerate(("bid_id", "package_id", "revision_id", "inventory_id", "id"), 1)
    }
    doc = {
        "document_version_id": uid(10),
        "parse_id": uid(11),
        "digest": "a" * 64,
        "blocks": [
            {
                "id": uid(12),
                "digest": "b" * 64,
                "physical_page": 2,
                "text_content": "private fact evidence",
            },
            {
                "id": uid(13),
                "digest": "c" * 64,
                "physical_page": 3,
                "text_content": "unselected private evidence",
            },
        ],
    }
    return FrozenPackageReviewInput(json.dumps(m), json.dumps({"documents": [doc]}), digest(m))


def test_selection_owns_exact_frozen_refs_and_contains_no_text_or_authority(packet):
    result = policy.select(packet, packet.digest, [uid(12)])
    view = result.view()
    assert result.digest == digest(view)
    assert view["selected"][0]["parse_run_id"] == uid(11)
    assert all(
        view[key] is False
        for key in (
            "original_bytes_verified",
            "facts_qualified",
            "review_ready",
            "launch_available",
            "publication_authorized",
        )
    )
    assert "private" not in json.dumps(view) and uid(13) not in json.dumps(view)
    view["selected"].clear()
    assert len(result.view()["selected"]) == 1
    assert "selected" not in repr(result)


@pytest.mark.parametrize(
    "ids",
    [
        [],
        None,
        "not-a-list",
        [uid(999)],
        [uid(12), uid(12)],
        ["AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"],
        [True],
        ["not-an-id"],
        [uid(12)] * 501,
    ],
)
def test_unknown_duplicate_or_malformed_selection_rejected(packet, ids):
    with pytest.raises(DomainError):
        policy.select(packet, packet.digest, ids)


def test_different_frozen_digest_cannot_be_substituted(packet):
    with pytest.raises(DomainError) as error:
        policy.select(packet, "0" * 64, [uid(12)])
    assert error.value.code == "PACKAGE_REVIEW_FROZEN_INPUT_CHANGED"


def test_order_is_stable_and_root_scope_changes_identity(packet):
    a = policy.select(packet, packet.digest, [uid(12), uid(13)])
    b = policy.select(packet, packet.digest, [uid(13), uid(12)])
    assert a.view() == b.view() and a.digest == b.digest
    m = packet.view()["manifest"]
    m["inventory_id"] = uid(999)
    other = FrozenPackageReviewInput(json.dumps(m), packet._evidence_text, digest(m))
    assert policy.select(other, other.digest, [uid(12), uid(13)]).digest != a.digest


@pytest.mark.parametrize("ambiguous", [False, True])
def test_same_evidence_reused_by_two_roles_is_deduplicated_only_if_identical(packet, ambiguous):
    root = packet.evidence()
    other = deepcopy(root["documents"][0])
    if ambiguous:
        other["parse_id"] = uid(999)
    root["documents"].append(other)
    value = FrozenPackageReviewInput(packet._manifest_text, json.dumps(root), packet.digest)
    if ambiguous:
        with pytest.raises(DomainError):
            policy.select(value, value.digest, [uid(12)])
    else:
        assert len(policy.select(value, value.digest, [uid(12)]).view()["selected"]) == 1
