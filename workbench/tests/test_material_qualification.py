"""Synthetic metadata only: never supplier evidence or accuracy validation."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_package_material_cost import policy_data

from packages.domain.errors import DomainError
from packages.model_governance import material_qualification as q
from packages.model_governance import package_technical_complete_vision as vision


def document():
    return {
        "version": q.VERSION,
        "binding": {
            **{k: str(uuid4()) for k in q.IDS},
            **{k: "a" * 64 for k in q.DIGESTS},
            "profile_digest": vision.profile_digest(),
            "serializer_digest": vision.serializer_digest(),
            "judgment_method_digest": vision.judgment_method_digest(),
        },
        "price": policy_data(),
        "evidence": {
            k: {
                "document_version_id": str(uuid4()),
                "digest": "b" * 64,
                "note": "Synthetic mechanism fixture",
            }
            for k in ("price", "capacity", "validation")
        },
        "requests": [
            {
                "rule_id": str(uuid4()),
                "request_digest": "c" * 64,
                "body_byte_count": 100,
                "input_tokens": 200,
            }
        ],
        "valid_from": "2026-10-24T00:00:00Z",
        "valid_until": "2026-10-25T00:00:00Z",
    }


def test_closed_document_copied_without_authority_flags():
    original = document()
    checked = q.validate(original)
    assert checked == original and checked is not original
    assert "execution_authorized" not in checked


@pytest.mark.parametrize("field", sorted(q.IDS | q.DIGESTS))
def test_bad_binding(field):
    value = document()
    value["binding"][field] = None
    with pytest.raises(DomainError):
        q.validate(value)


@pytest.mark.parametrize(
    "path,value",
    [
        (("version",), "material-qualification-review/2"),
        (("verified",), True),
        (("price", "input_per_million_minor"), None),
        (("price", "model_alias"), "other"),
        (("evidence",), {}),
        (("evidence", "price", "note"), " "),
        (("requests",), []),
        (("requests", 0, "input_tokens"), True),
        (("requests", 0, "input_tokens"), 1048576),
        (("requests", 0, "body_byte_count"), 100000000),
        (("valid_until",), "2026-10-26T00:00:00Z"),
        (("valid_from",), "2026-10-24T00:00:00"),
    ],
)
def test_rejects_incomplete_unknown_or_oversized_claims(path, value):
    original = document()
    target = original
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(DomainError):
        q.validate(original)


def test_duplicate_rules_rejected():
    value = document()
    value["requests"].append(deepcopy(value["requests"][0]))
    with pytest.raises(DomainError):
        q.validate(value)


def test_approval_window_and_terminal_revocation():
    value = document()
    approved = {"decision": "approved", "reason": "Reviewed synthetic fixture"}
    at = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    assert q.transition(value, None, approved, at) == "approved"
    for previous in ("approved", "revoked"):
        with pytest.raises(DomainError):
            q.transition(value, previous, approved, at)
    for day in (23, 25):
        with pytest.raises(DomainError):
            q.transition(value, None, approved, at.replace(day=day))
    # Revocation is possible even after method drift or expiry.
    value["binding"]["profile_digest"] = "e" * 64
    assert (
        q.transition(
            value, "approved", {"decision": "revoked", "reason": "Withdrawn"}, at.replace(day=26)
        )
        == "revoked"
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"decision": "approved", "reason": ""},
        {"decision": "approved", "reason": "x", "verified": True},
        {"decision": [], "reason": "x"},
    ],
)
def test_decision_malformed(body):
    with pytest.raises(DomainError):
        q.decision(body)


def test_padded_reason_and_note_are_bounded_before_sql():
    with pytest.raises(DomainError):
        q.decision({"decision": "approved", "reason": "x" + " " * 4000})
    value = document()
    value["evidence"]["price"]["note"] = "x" + " " * 4000
    with pytest.raises(DomainError):
        q.validate(value)
