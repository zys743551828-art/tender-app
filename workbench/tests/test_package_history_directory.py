"""Closed metadata discovery boundaries; real ACL and snapshot checks are separate."""

import base64
import json
from copy import deepcopy

import pytest

from packages.contracts import package_history_directory_api as contract
from packages.domain.runtime import DomainError, secret_hash, sha
from packages.model_governance import package_history_directory as directory

FILTERS = {"bid_id": None, "scope_id": None, "protocol_id": None, "cohort_id": None}
AFTER = "00000000-0000-0000-0000-000000000001"
OBSERVATION = "a" * 64


@pytest.fixture(autouse=True)
def cursor_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "explicit-synthetic-history-directory-cursor-secret")


def signed(value):
    raw = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    token = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return token + "." + secret_hash("package-history-directory/1:" + token)


def test_cursor_binds_exact_directory_filters_and_full_observation():
    token = directory.encode_cursor("protocols", FILTERS, OBSERVATION, AFTER)
    assert directory.decode_cursor(token, "protocols", FILTERS) == (AFTER, OBSERVATION)
    assert directory.decode_cursor(None, "protocols", FILTERS) == (None, None)
    for kind, filters in (
        ("cohorts", FILTERS),
        ("protocols", FILTERS | {"bid_id": AFTER}),
    ):
        with pytest.raises(DomainError) as error:
            directory.decode_cursor(token, kind, filters)
        assert error.value.status == 422
    with pytest.raises(DomainError):
        directory.decode_cursor(token + "x", "protocols", FILTERS)


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"scope": "b" * 64},
        {"observation": "latest"},
        {"after": "current"},
        {"after": AFTER.upper().replace("000000000001", "ABCDEFABCDEF")},
        {"unreviewed_extra": True},
    ],
)
def test_even_signed_cursor_payloads_require_closed_canonical_identity(change):
    payload = {
        "version": 1,
        "scope": sha({"kind": "protocols", "filters": FILTERS}),
        "observation": OBSERVATION,
        "after": AFTER,
    } | change
    with pytest.raises(DomainError):
        directory.decode_cursor(signed(payload), "protocols", FILTERS)


def test_duplicate_json_keys_are_not_resolved_by_last_value():
    payload = json.dumps(
        {
            "version": 1,
            "scope": sha({"kind": "protocols", "filters": FILTERS}),
            "observation": OBSERVATION,
            "after": AFTER,
        }
    )
    with pytest.raises(DomainError):
        directory.decode_cursor(signed('{"version":1,' + payload[1:]), "protocols", FILTERS)


@pytest.mark.parametrize("kind", tuple(contract.NAMES))
def test_missing_schema_is_unavailable_with_unknown_counts_not_an_empty_observation(kind):
    value = directory.unavailable(kind, FILTERS)
    assert contract.validate(kind, value) is value
    assert value["total"] is None and value["has_more"] is None
    assert not value["complete_observation"] and value["formal_eligibility"] == "unavailable"
    for changes in (
        {"total": 0},
        {"has_more": False},
        {"qualification_granted": True},
        {"currentness_rechecked": True},
        {"official_technical_value": "0"},
    ):
        with pytest.raises(DomainError):
            contract.validate(kind, deepcopy(value) | changes)


@pytest.mark.parametrize(
    "kind,options",
    [
        ("admissions", {"scope": AFTER}),
        ("protocols", {"bid": AFTER}),
        ("cohorts", {"cohort": AFTER}),
        ("jobs", {}),
        ("jobs", {"cohort": AFTER, "scope": AFTER}),
        ("protocols", {"limit": True}),
        ("cohorts", {"protocol": "latest"}),
    ],
)
def test_invalid_directory_requests_are_rejected_before_any_database_read(
    kind, options, monkeypatch
):
    def forbidden_connection():
        raise AssertionError("invalid identity must not open a database")

    monkeypatch.setattr(directory, "connection", forbidden_connection)
    with pytest.raises(DomainError) as error:
        directory.read(kind, **options)
    assert error.value.status == 422
