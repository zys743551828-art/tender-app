"""Exact package result protocol and fail-closed source boundaries, without IO."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from packages.contracts import package_outcomes_api as contract
from packages.domain.runtime import DomainError, sha
from packages.rag.indexing import original_source_id, parse_source_id
from packages.research import outcomes
from packages.research import package_outcomes as domain


def identity(number):
    return str(UUID(int=number))


def case(*, authority=True, confirmed=True):
    original = {
        "identity_version": "bid-identity/2",
        "bidder_id": identity(1),
        "bidder_name": "Synthetic bidder",
        "round_id": identity(2),
        "engineering_project_id": identity(3),
        "engineering_title": "Synthetic engineering",
        "region": None,
        "engineering_type": None,
        "lot": "Synthetic lot",
        "lot_id": identity(4),
        "round_no": 1,
        "binding_status": "confirmed" if confirmed else "pending",
        "authority_id": identity(5) if confirmed else None,
    }
    original["digest"] = sha(original)
    source = {
        "manifest": {
            "package_id": identity(10),
            "revision_id": identity(11),
            "members": [
                {
                    "document_version_id": identity(12),
                    "file_digest": "1" * 64,
                    "parse": {
                        "status": "frozen",
                        "parse_run_id": identity(13),
                        "parser_digest": "2" * 64,
                        "config_digest": "3" * 64,
                        "evidence_digest": "4" * 64,
                        "reason": None,
                    },
                }
            ],
        },
        "digest": "a" * 64,
        "identity": original,
    }
    frozen = {
        "manifest": {
            "bid_id": identity(20),
            "submission_id": identity(21),
            "subject": {
                "kind": "bid_package",
                "bid_id": identity(20),
                "package_id": identity(22),
                "revision_id": identity(23),
                "package_digest": "b" * 64,
            },
            "package_identity": original,
            "recorded_identity": original | {"bidder_name": "Later changed display"},
            "selection": {"authority": source if authority else None},
        },
        "digest": "c" * 64,
    }
    request = {
        "version": "package-outcome-verification/1",
        "subject_kind": "bid_package",
        "state": "pending",
        "reason": "Synthetic careful outcome association",
        "identity": domain.identity_for(frozen),
        "authority": domain.authority_for(frozen),
        "aggregation": "Official technical total",
        "published_at": "2026-10-20T01:00:00Z",
        "evidence_refs": [
            {
                "document_version_id": identity(30),
                "evidence_id": identity(31),
                "physical_page": 1,
                "quote": "Synthetic official technical score 0/60.",
            }
        ],
    }
    return frozen, request


def graph():
    frozen, _ = case()
    authority = frozen["manifest"]["selection"]["authority"]
    original = str(original_source_id(UUID(identity(12))))
    parsed = str(parse_source_id(UUID(identity(13))))
    nodes = [
        {
            "id": key,
            "document_version_id": identity(12),
            "digest": "1" * 64,
            "kind": "document",
            "policy_class": "prebid_content",
        }
        for key in (original, parsed)
    ]
    rows = [
        {
            "source_id": source,
            "ancestor_id": ancestor,
            "document_version_id": identity(12),
            "kind": "document",
            "digest": "1" * 64,
            "policy_class": "prebid_content",
            "known_at": "2026-10-19T00:00:00+00:00",
            "revision": 2,
            "status": "published",
            "valid_from": "2026-10-19T00:00:00+00:00",
            "valid_until": None,
        }
        for source, ancestor in ((original, original), (parsed, original), (parsed, parsed))
    ]
    frozen_sources = [{k: v for k, v in row.items() if k not in {"kind", "digest"}} for row in rows]
    return authority, frozen_sources, nodes, rows


def check_graph(values):
    return domain.check_authority_sources(
        *values,
        checked_at="2026-10-21T01:00:00Z",
        submitted_at="2026-10-20T00:00:00Z",
    )


@pytest.mark.parametrize("state", contract.STATES)
def test_request_states_bind_original_identity_and_return_independent_copy(state):
    frozen, body = case()
    body["state"] = state
    checked = domain.verification_request(body, frozen)
    assert checked == body and checked is not body
    checked["identity"]["identity_digest"] = "0" * 64
    assert checked != body
    assert body["identity"]["identity_digest"] == frozen["manifest"]["package_identity"]["digest"]


@pytest.mark.parametrize("state", ["pending", "conflict", "rejected"])
def test_missing_authority_keeps_nonverified_observation_usable(state):
    frozen, body = case(authority=False, confirmed=False)
    body.update(state=state, published_at=None, aggregation="", evidence_refs=[])
    assert domain.verification_request(body, frozen) == body


def test_missing_authority_cannot_be_upgraded_by_identity_or_checkbox():
    frozen, body = case(authority=False)
    body["state"] = "verified"
    with pytest.raises(DomainError) as caught:
        domain.verification_request(body, frozen)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_MISSING"
    body["effective_material_confirmed"] = True
    assert not contract.valid("PackageOutcomeVerificationRequest", body)


@pytest.mark.parametrize("field", list(case()[1]["identity"]))
def test_every_identity_component_is_bound_even_for_rejection(field):
    frozen, body = case()
    body["state"] = "rejected"
    body["identity"][field] = "e" * 64 if field.endswith("digest") else identity(99)
    with pytest.raises(DomainError) as caught:
        domain.verification_request(body, frozen)
    assert caught.value.code == "PACKAGE_OUTCOME_IDENTITY_MISMATCH"


@pytest.mark.parametrize("field", ["package_id", "revision_id", "digest", "identity_digest"])
def test_every_authority_component_is_bound(field):
    frozen, body = case()
    body["authority"][field] = "e" * 64 if field.endswith("digest") else identity(99)
    with pytest.raises(DomainError) as caught:
        domain.verification_request(body, frozen)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_MISMATCH"


@pytest.mark.parametrize("field", ["aggregation", "published_at", "evidence_refs"])
def test_verified_requires_meaningful_official_page_and_time(field):
    frozen, body = case()
    body["state"] = "verified"
    body[field] = {"aggregation": "  ", "published_at": None, "evidence_refs": []}[field]
    with pytest.raises(DomainError) as caught:
        domain.verification_request(body, frozen)
    assert caught.value.code == "PACKAGE_OUTCOME_SOURCE_INCOMPLETE"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("subject_kind",), "single_body"),
        (("version",), "package-outcome-verification/2"),
        (("state",), "approved"),
        (("reason",), " "),
        (("reason",), "x" * 4001),
        (("aggregation",), "x" * 201),
        (("published_at",), "2026-10-21T10:00:00"),
        (("identity", "revision_id"), "not-a-uuid"),
        (("identity", "identity_digest"), "A" * 64),
        (("identity", "body_version_id"), identity(99)),
        (("evidence_refs", 0, "quote"), ""),
        (("evidence_refs", 0, "quote"), " "),
        (("evidence_refs", 0, "quote"), "x" * 4001),
        (("evidence_refs", 0, "physical_page"), 0),
        (("evidence_refs", 0, "physical_page"), True),
        (("evidence_refs", 0, "claimed_verified"), True),
    ],
)
def test_contract_rejects_malformed_and_invented_authority_fields(path, value):
    _, body = case()
    parent = body
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    assert not contract.valid("PackageOutcomeVerificationRequest", body)


def test_reference_capacity_and_duplicate_limits_are_not_truncated():
    _, body = case()
    body["evidence_refs"] *= 2
    assert not contract.valid("PackageOutcomeVerificationRequest", body)
    body["evidence_refs"] = [
        body["evidence_refs"][0] | {"evidence_id": identity(100 + i)} for i in range(101)
    ]
    assert not contract.valid("PackageOutcomeVerificationRequest", body)
    body["evidence_refs"].pop()
    assert contract.valid("PackageOutcomeVerificationRequest", body)


@pytest.mark.parametrize(
    "times",
    [
        (
            "2026-10-20T00:00:00Z",
            "2026-10-21T01:00:00Z",
            "2026-10-19T00:00:00Z",
            "2026-10-22T00:00:00Z",
        ),
        (
            "2026-10-20T00:00:00Z",
            "2026-10-21T01:00:00Z",
            "2026-10-22T00:00:00Z",
            "2026-10-23T00:00:00Z",
        ),
        (
            "2026-10-20T00:00:00Z",
            "2026-10-23T00:00:00Z",
            "2026-10-21T00:00:00Z",
            "2026-10-22T00:00:00Z",
        ),
        (
            "2026-10-20T00:00:00",
            "2026-10-21T01:00:00Z",
            "2026-10-21T00:00:00Z",
            "2026-10-22T00:00:00Z",
        ),
        (None, "2026-10-21T01:00:00Z", "2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z"),
        ("garbage", "2026-10-21T01:00:00Z", "2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z"),
    ],
)
def test_time_order_cannot_promote_late_or_unknown_information(times):
    with pytest.raises(DomainError) as caught:
        domain.check_times(*times)
    assert caught.value.code == "PACKAGE_OUTCOME_TIME_INVALID"


def test_equal_instants_different_offsets_are_valid():
    domain.check_times(
        "2026-10-21T08:00:00+08:00",
        "2026-10-21T00:00:00Z",
        "2026-10-21T00:00:00+00:00",
        datetime(2026, 10, 21, tzinfo=timezone.utc),
    )


def test_exact_authority_graph_allows_order_independent_read():
    values = graph()
    check_graph(values)
    values[1].reverse()
    values[3].reverse()
    check_graph(values)


def test_source_timestamp_encodings_compare_same_instant_without_mutating_history():
    values = graph()
    values[1][0]["known_at"] = "2026-10-19T08:00:00.12345+08:00"
    values[3][0]["known_at"] = "2026-10-19T00:00:00.123450+00:00"
    before = deepcopy(values[1])
    check_graph(values)
    assert values[1] == before
    values[3][0]["known_at"] = "2026-10-19T00:00:00.123451+00:00"
    with pytest.raises(DomainError) as caught:
        check_graph(values)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_SOURCE_CHANGED"


@pytest.mark.parametrize("which", ["nodes", "closure", "self", "duplicate", "frozen"])
def test_missing_ancestry_and_duplicate_source_rows_do_not_count_as_proof(which):
    values = list(graph())
    if which == "nodes":
        values[2].pop()
    elif which == "closure":
        values[3].clear()
    elif which == "self":
        values[3].pop()
    elif which == "duplicate":
        values[3].append(deepcopy(values[3][-1]))
    else:
        values[1].pop()
    with pytest.raises(DomainError):
        check_graph(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "rule"),
        ("digest", "8" * 64),
        ("policy_class", "official_label"),
        ("document_version_id", identity(99)),
    ],
)
def test_direct_source_must_be_exact_original(field, value):
    values = graph()
    values[2][0][field] = value
    with pytest.raises(DomainError) as caught:
        check_graph(values)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_SOURCE_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "fact"),
        ("document_version_id", None),
        ("policy_class", "official_label"),
        ("status", "withdrawn"),
        ("status", "candidate"),
        ("revision", None),
        ("known_at", None),
        ("known_at", "2026-10-20T00:00:01Z"),
        ("valid_from", None),
        ("valid_from", "2026-10-20T00:00:01Z"),
        ("valid_until", "2026-10-21T01:00:00Z"),
    ],
)
def test_ancestor_effectivity_is_required_even_when_frozen_with_invalid_state(field, value):
    values = graph()
    values[3][1][field] = value
    if field not in {"kind", "digest"}:
        values[1][1][field] = value
    with pytest.raises(DomainError) as caught:
        check_graph(values)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_SOURCE_INVALID"


def test_source_revision_change_cannot_reuse_old_binding():
    values = graph()
    values[3][1]["revision"] += 1
    with pytest.raises(DomainError) as caught:
        check_graph(values)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_SOURCE_CHANGED"


def test_authority_capacity_fails_whole_observation(monkeypatch):
    monkeypatch.setattr(domain, "MAX_SOURCE_ROWS", 2)
    with pytest.raises(DomainError) as caught:
        check_graph(graph())
    assert caught.value.code == "PACKAGE_OUTCOME_CAPACITY_EXCEEDED"


class Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


def test_sample_rejection_happens_before_any_outcome_lookup_or_insert():
    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, query, params=()):
            self.calls.append(query)
            assert query.startswith("SELECT * FROM submission_records")
            return Result({"subject_kind": "bid_package"})

    c = Connection()
    with pytest.raises(DomainError) as caught:
        outcomes.admissibility(c, identity(20), identity(21))
    assert caught.value.code == "PACKAGE_OUTCOME_FORMAL_SAMPLE_UNSUPPORTED"
    assert caught.value.details == {
        "reasons": ["package_formal_sample_not_supported"],
        "sample_created": False,
    }
    assert len(c.calls) == 1


@pytest.mark.parametrize("subject", [{}, {"subject_kind": "single_body"}])
def test_legacy_sample_guard_remains_compatible(subject):
    assert domain.reject_formal_sample(subject) is None


@pytest.mark.parametrize("state", ["pending", "conflict", "rejected"])
def test_nonverified_adapter_retains_original_identity_without_promoting_it(monkeypatch, state):
    frozen, body = case(authority=False, confirmed=False)
    body.update(state=state, evidence_refs=[], published_at=None)
    monkeypatch.setattr(domain, "require_registration", lambda *_: frozen)
    monkeypatch.setattr(
        domain,
        "require_submission_identity",
        lambda *_: pytest.fail("nonverified facts must not require current identity confirmation"),
    )
    c = SimpleNamespace(
        execute=lambda *_: Result({"at": datetime(2026, 10, 21, tzinfo=timezone.utc)})
    )
    native = {"id": identity(21), "bid_id": identity(20)}
    outcome = {"submission_id": identity(21), "bid_id": identity(20)}
    value = domain.verification(c, native, outcome, body)
    assert value["evidence_ids"] == []
    details = value["details"]
    assert contract.valid("PackageOutcomeVerificationDetails", details)
    assert details["package_identity"] == frozen["manifest"]["package_identity"]
    assert details["package_identity"] != frozen["manifest"]["recorded_identity"]
    assert details["authority_proof"] is details["official_source_proof"] is None
    assert not details["formal_sample_eligible"]


@pytest.mark.parametrize("field", ["bid_id", "submission_id"])
def test_adapter_refuses_cross_bid_or_other_submission_before_evidence_read(monkeypatch, field):
    frozen, body = case()
    monkeypatch.setattr(domain, "require_registration", lambda *_: frozen)
    native = {"id": identity(21), "bid_id": identity(20)}
    outcome = {"submission_id": identity(21), "bid_id": identity(20)}
    outcome[field] = identity(99)
    with pytest.raises(DomainError) as caught:
        domain.verification(None, native, outcome, body)
    assert caught.value.code == "PACKAGE_OUTCOME_SUBJECT_MISMATCH"


@pytest.mark.parametrize(
    "mutation", ["document", "request_document", "page", "quote", "digest", "missing"]
)
def test_even_rejected_opinions_require_exact_official_page_quotes(mutation):
    _, body = case()
    ref = body["evidence_refs"][0]
    text = ref["quote"]
    row = {
        "document_version_id": UUID(identity(30)),
        "physical_page": 1,
        "text_content": text,
        "digest": sha(text.encode()),
    }
    if mutation == "document":
        row["document_version_id"] = UUID(identity(99))
    elif mutation == "request_document":
        ref["document_version_id"] = identity(99)
    elif mutation == "page":
        ref["physical_page"] = 2
    elif mutation == "quote":
        ref["quote"] = "Fabricated official result"
    elif mutation == "digest":
        row["digest"] = "0" * 64
    else:
        row = None
    c = SimpleNamespace(execute=lambda *_: Result(row))
    with pytest.raises(DomainError) as caught:
        domain._references(c, {"bid_id": identity(20), "source_version_id": identity(30)}, [ref])
    assert caught.value.code == "PACKAGE_OUTCOME_SOURCE_MISMATCH"


def test_openapi_registration_preserves_shared_research_operations():
    operation = {"operationId": "verifyOutcome"}
    actual = {"components": {"schemas": {}}, "paths": {"synthetic": operation}}
    contract.extend_openapi(actual)
    assert actual["paths"]["synthetic"] is operation
    assert set(contract.SCHEMAS) <= set(actual["components"]["schemas"])


def read_case():
    frozen, body = case()
    body["state"] = "verified"
    details = {
        "version": "package-outcome-verification-record/1",
        "subject_kind": "bid_package",
        "request": body,
        "package_identity": frozen["manifest"]["package_identity"],
        "binding_digest": frozen["digest"],
        "checked_at": "2026-10-21T02:00:00Z",
        "authority_proof": {"digest": sha({}), "snapshot": {}},
        "official_source_proof": {"digest": sha({}), "snapshot": {}},
        "verification_scope": "official_outcome_association",
        "formal_sample_eligible": False,
        "formal_sample_blockers": [contract.SAMPLE_REASON],
    }
    submission = {
        "id": identity(21),
        "bid_id": identity(20),
        "subject_kind": "bid_package",
        "submitted_at": "2026-10-20T00:00:00Z",
        "created_at": "2026-10-20T00:00:01Z",
    }
    outcome = {
        "id": identity(25),
        "bid_id": identity(20),
        "submission_id": identity(21),
        "known_at": "2026-10-21T01:00:00Z",
    }
    decision = {
        "decision": "verified",
        "object_kind": "outcome",
        "object_id": identity(25),
        "object_revision": 1,
        "evidence_ids": [identity(31)],
        "created_at": "2026-10-21T02:00:01Z",
    }
    head = {"outcome_id": identity(25), "revision": 1}

    class ReadOnly:
        def execute(self, query, parameters=()):
            if "clock_timestamp" in query:
                return Result({"at": datetime(2026, 10, 21, 3, tzinfo=timezone.utc)})
            if "decision_heads" in query:
                return Result(decision | {"reason": json.dumps(details)})
            if "outcome_heads" in query:
                return Result(head)
            pytest.fail("Rejected current observation must not read downstream authority")

    return ReadOnly(), submission, outcome, details, decision, head


@pytest.mark.parametrize(
    "field", ["submitted_at", "created_at", "known_at", "checked_at", "decision_created_at"]
)
def test_current_eligibility_never_sees_a_record_after_as_of(field):
    c, submission, outcome, details, decision, _ = read_case()
    at = "2026-10-21T03:00:00Z"
    future = "2026-10-22T00:00:00Z"
    if field in {"submitted_at", "created_at"}:
        submission[field] = future
    elif field == "known_at":
        outcome[field] = future
    elif field == "checked_at":
        details[field] = future
    else:
        decision["created_at"] = future
    assert domain.current_reasons(c, submission, outcome, details, as_of=at) == [
        "package_outcome_not_observed_at_as_of"
    ]


def test_future_as_of_cannot_make_future_records_visible():
    c, submission, outcome, details, _, _ = read_case()
    outcome["known_at"] = "2026-10-22T00:00:00Z"
    assert domain.current_reasons(
        c, submission, outcome, details, as_of="2026-10-23T00:00:00Z"
    ) == ["package_outcome_not_observed_at_as_of"]


@pytest.mark.parametrize("field", ["object_kind", "object_id", "decision", "evidence_ids"])
def test_current_eligibility_reads_exact_native_decision(field):
    c, submission, outcome, details, decision, _ = read_case()
    decision[field] = {
        "object_kind": "rule",
        "object_id": identity(99),
        "decision": "rejected",
        "evidence_ids": [identity(31), identity(31)],
    }[field]
    assert domain.current_reasons(c, submission, outcome, details) == [
        "package_outcome_verification_changed"
    ]


@pytest.mark.parametrize("field", ["outcome_id", "revision"])
def test_current_eligibility_does_not_fall_back_to_old_verified_outcome(field):
    c, submission, outcome, details, _, head = read_case()
    head[field] = identity(99) if field == "outcome_id" else 2
    assert domain.current_reasons(c, submission, outcome, details) == [
        "package_outcome_not_current"
    ]


def test_malformed_or_nonverified_details_cannot_be_current_authority():
    assert domain.current_reasons(None, {}, {}, None) == ["package_outcome_verification_unproven"]
    _, submission, outcome, details, _, _ = read_case()
    details["request"]["state"] = "rejected"
    assert domain.current_reasons(None, submission, outcome, details) == [
        "package_outcome_not_verified"
    ]
