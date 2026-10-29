"""Synthetic immutable scope protocol; these tests grant no database or factual authority."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from packages.domain import package_fact_scope as scope
from packages.domain.fact_sets import identity as fact_identity
from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


@pytest.fixture
def case():
    identity = {
        "bidder_id": uid(20),
        "bidder_name": "同名主体",
        "round_id": uid(21),
        "engineering_project_id": uid(22),
        "engineering_title": "同名工程",
        "region": None,
        "engineering_type": None,
        "lot": "同名标段",
        "lot_id": uid(23),
        "round_no": 1,
        "binding_status": "confirmed",
        "authority_id": uid(24),
        "identity_version": "bid-identity/2",
    }
    identity["digest"] = digest(identity)
    fact = {
        "id": uid(30),
        "bid_id": uid(1),
        "fact_set_id": uid(31),
        "subject": "自由文本不会选主体",
        "scope": "同名标段不会选标段",
        "name": "数量",
        "value_jsonb_text": '{"amount":1.25}',
        "unit": None,
        "evidence_ids": [uid(32)],
    }
    proof = {
        "decision_binding": True,
        "references": [{"evidence_id": uid(32), "source_revision": 1}],
        "closure": [{"id": uid(33), "status": "published", "revision": 1}],
        "sources_effective": True,
        "evidence_usable": True,
    }
    basis = {
        "fact_identity": fact_identity({**fact, "value": {"amount": 1.25}}),
        "evidence": {
            "references": proof["references"],
            "source_closure_digest": digest(proof["closure"]),
        },
    }
    item = {
        "fact": fact,
        "decision": {"id": uid(34), "decision": "confirmed"},
        "decision_basis_jsonb_text": json.dumps(basis),
        "scope_binding": "selected_frozen_parse",
    }
    facts = {
        "version": "package-review-facts/1",
        "head": {"fact_set_id": uid(31), "revision": 1, "fact_set_digest": "a" * 64},
        "items": [item],
        "value_encoding": "postgresql-jsonb-text",
        "qualification": "not_validated",
    }
    cm = {
        "identity": identity,
        "facts": facts,
        "facts_digest": digest(facts),
        "as_of": "2026-10-20T00:00:00.000000Z",
    }
    context = {
        "manifest": cm,
        "semantic_digest": digest({k: v for k, v in cm.items() if k != "as_of"}),
        "snapshot_digest": digest(cm),
    }
    binding = {
        **dict(
            zip(
                ("bid_id", "package_id", "revision_id", "inventory_id"),
                [uid(n) for n in range(1, 5)],
                strict=True,
            )
        ),
        "identity_digest": identity["digest"],
        "frozen_input_id": uid(5),
        "frozen_digest": "b" * 64,
        "input_digest": "c" * 64,
        "evidence_digest": "d" * 64,
        "context_digest": context["semantic_digest"],
        "method_digest": "e" * 64,
        "policy_digest": "f" * 64,
        "purpose": "prebid_compliance",
    }
    current = {
        "binding": binding,
        "context": context,
        "observations": {"head": "exact"},
        "documents": [{"parse_id": uid(35), "object_key": "private-object"}],
        "result": {
            "checked_at": cm["as_of"],
            "current_context": {
                "as_of": cm["as_of"],
                "snapshot_digest": context["snapshot_digest"],
                "semantic_digest": context["semantic_digest"],
            },
            "blockers": ["FACTS_UNPROVEN"],
            "review_ready": False,
        },
    }
    packet = PreparedExecutionInput(
        tuple(binding[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")),
        uid(5),
        uid(6),
        "1" * 64,
        json.dumps({"manifest": {"identity": {"binding": binding}}}),
        json.dumps(current | {"version": "package-review-prepared-snapshot/1"}),
    )
    audit = {
        "record_id": uid(40),
        "actor_id": uid(41),
        "command_id": uid(42),
        "recorded_at": "2026-10-20T00:00:00.000000Z",
        "reason": "人工核对事实适用对象",
    }
    return {
        "packet": packet,
        "current": current,
        "fact_id": fact["id"],
        "proof": proof,
        "subject": {"kind": "lot", "id": uid(23)},
        "audit": audit,
    }


def declare(case, **extra):
    return scope.declare(
        **{k: v for k, v in case.items() if k != "audit"}, **case["audit"], **extra
    )


def test_explicit_subject_owns_new_record_and_never_rewrites_prepared(case):
    before = case["packet"].snapshot()
    record = declare(case)
    assert record["manifest"]["subject"] == {"kind": "lot", "id": uid(23)}
    assert record["manifest"]["binding"]["execution_input_id"] == uid(6)
    assert all(
        record["manifest"][k] is False
        for k in ("facts_qualified", "review_ready", "launch_available", "publication_authorized")
    )
    assert case["packet"].snapshot() == before
    assert before["context"]["manifest"]["facts"]["qualification"] == "not_validated"
    assert "private-object" not in json.dumps(record) and "amount" not in json.dumps(record)
    assert (
        scope.current_status(
            record, **{k: v for k, v in case.items() if k not in {"audit", "subject"}}
        )
        == "matches_current_input"
    )
    case["subject"]["id"] = uid(999)
    assert record["manifest"]["subject"]["id"] == uid(23)
    copy = scope.verify(record)
    copy["manifest"]["subject"]["id"] = uid(999)
    assert record["manifest"]["subject"]["id"] == uid(23)


@pytest.mark.parametrize("kind,field", scope.SUBJECTS.items())
def test_all_supported_structured_subjects_are_explicit(case, kind, field):
    case["subject"] = {
        "kind": kind,
        "id": case["current"]["context"]["manifest"]["identity"][field],
    }
    assert declare(case)["manifest"]["subject"] == case["subject"]


@pytest.mark.parametrize(
    "change",
    [
        "subject",
        "missing_subject",
        "arbitrary_kind",
        "extra_authority",
        "upper_uuid",
        "timestamp",
        "reason",
        "action",
    ],
)
def test_no_text_matching_or_injected_authority(case, change):
    if change == "subject":
        case["subject"]["id"] = uid(999)
    if change == "missing_subject":
        case["subject"] = {}
    if change == "arbitrary_kind":
        case["subject"]["kind"] = "all"
    if change == "extra_authority":
        case["subject"]["facts_qualified"] = True
    if change == "upper_uuid":
        case["audit"]["record_id"] = "AAAAAAAA-0000-4000-8000-000000000001"
    if change == "timestamp":
        case["audit"]["recorded_at"] = "2026-10-20T08:00:00+08:00"
    if change == "reason":
        case["audit"]["reason"] = " 说明 "
    if change == "action":
        case["subject"]["kind"] = "同名标段"
    with pytest.raises(ValueError):
        declare(case)


@pytest.mark.parametrize(
    "change",
    ["fact", "decision", "basis", "scope", "identity", "source", "document", "head", "blockers"],
)
def test_any_prepared_private_input_change_invalidates_new_binding(case, change):
    current = case["current"]
    item = current["context"]["manifest"]["facts"]["items"][0]
    if change == "fact":
        item["fact"]["value_jsonb_text"] = "2"
    if change == "decision":
        item["decision"]["id"] = uid(99)
    if change == "basis":
        item["decision_basis_jsonb_text"] = "{}"
    if change == "scope":
        current["binding"]["revision_id"] = uid(99)
    if change == "identity":
        current["context"]["manifest"]["identity"]["bidder_id"] = uid(99)
    if change == "source":
        current["observations"]["source"] = "withdrawn"
    if change == "document":
        current["documents"][0]["parse_id"] = uid(99)
    if change == "head":
        current["observations"]["head"] = "new"
    if change == "blockers":
        current["result"]["blockers"] = []
    with pytest.raises((ValueError, DomainError)):
        declare(case)


def test_observation_time_only_does_not_change_input_binding(case):
    old = declare(case)
    current = case["current"]
    current["context"]["manifest"]["as_of"] = "2026-10-20T00:01:00.000000Z"
    current["context"]["snapshot_digest"] = "9" * 64
    current["result"]["checked_at"] = "2026-10-20T00:01:00.000000Z"
    current["result"]["current_context"]["as_of"] = "2026-10-20T00:01:00.000000Z"
    current["result"]["current_context"]["snapshot_digest"] = "9" * 64
    assert declare(case) == old


@pytest.mark.parametrize("field", ["decision_binding", "sources_effective", "evidence_usable"])
def test_fresh_provenance_required_even_for_unchanged_prepared_input(case, field):
    old = declare(case)
    case["proof"][field] = False
    with pytest.raises(ValueError, match="fact_scope_provenance"):
        declare(case)
    with pytest.raises(ValueError):
        scope.current_status(
            old, **{k: v for k, v in case.items() if k not in {"audit", "subject"}}
        )
    assert scope.verify(old) == old  # historical validation does not depend on today's source
    withdrawn = scope.withdraw(old, **(case["audit"] | {"record_id": uid(50)}))
    assert withdrawn["manifest"]["action"] == "withdraw"
    assert withdrawn["manifest"]["previous_digest"] == old["digest"]
    assert scope.current_status(withdrawn, None, None, None, None) == "withdrawn"


def test_append_replacement_withdrawal_and_rebind_are_explicit(case):
    first = declare(case)
    case["audit"]["record_id"] = uid(50)
    second = declare(case, previous=first)
    assert second["manifest"]["previous_digest"] == first["digest"]
    withdrawn = scope.withdraw(second, **(case["audit"] | {"record_id": uid(51)}))
    with pytest.raises(ValueError, match="already_withdrawn"):
        scope.withdraw(withdrawn, **case["audit"])
    case["audit"]["record_id"] = uid(52)
    third = declare(case, previous=withdrawn)
    assert third["manifest"]["action"] == "bind"
    assert third["manifest"]["previous_digest"] == withdrawn["digest"]


def test_foreign_predecessor_and_forged_digest_fail(case):
    first = declare(case)
    other = deepcopy(first)
    other["manifest"]["binding"]["execution_input_id"] = uid(999)
    other["digest"] = digest(other["manifest"])
    with pytest.raises(ValueError, match="fact_scope_predecessor"):
        declare(case, previous=other)
    first["manifest"]["reason"] = "伪造原因"
    with pytest.raises(ValueError, match="fact_scope_digest"):
        scope.verify(first)


@pytest.mark.parametrize(
    "field", ["facts_qualified", "review_ready", "launch_available", "publication_authorized"]
)
def test_record_cannot_be_resealed_as_authority(case, field):
    record = declare(case)
    record["manifest"][field] = True
    record["digest"] = digest(record["manifest"])
    with pytest.raises(ValueError, match="contract"):
        scope.verify(record)


def test_schema_and_withdrawal_predecessor_contract(case):
    Draft202012Validator.check_schema(scope.SCHEMA)
    record = declare(case)
    record["manifest"]["action"] = "withdraw"
    record["digest"] = digest(record["manifest"])
    with pytest.raises(ValueError, match="contract"):
        scope.verify(record)


def test_fixed_scope_identity_vectors(case):
    vectors = json.loads(
        (Path(__file__).parent / "fixtures/package-fact-scope-vectors.json").read_text("utf-8")
    )
    first = declare(case)
    case["audit"]["record_id"] = uid(50)
    second = declare(case, previous=first)
    third = scope.withdraw(second, **(case["audit"] | {"record_id": uid(51)}))
    assert [first, second, third] == [v["expected"] for v in vectors]
    assert all(scope.verify(v["expected"]) == v["expected"] for v in vectors)
