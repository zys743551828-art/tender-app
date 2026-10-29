"""Closed job/slot facts cannot self-authorize spending or execution."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import material_judgment_jobs as jobs


def sample():
    rules = [str(uuid4()), str(uuid4())]
    d = (
        {k: str(uuid4()) for k in jobs.UUID_FIELDS}
        | {k: "a" * 64 for k in jobs.SHA_FIELDS}
        | {k: True for k in jobs.TRUE_FIELDS}
        | {k: False for k in jobs.FALSE_FIELDS}
    )
    d.update(
        version="material-judgment-job/1",
        profile_head_revision=1,
        rule_ids=rules,
        slots=[
            {
                "slot_id": str(uuid4()),
                "rule_id": rule,
                "rule_ordinal": ordinal,
                "slot_number": number,
                "max_attempts": 5,
            }
            for ordinal, rule in enumerate(rules, 1)
            for number in range(1, 4)
        ],
        required_valid_slots=6,
        max_attempts_per_slot=5,
        maximum_external_calls=30,
        currency="USD",
        required_reservation_minor=300,
        budget_ceiling_minor=500,
        origin="synthetic_mechanism",
        generation=1,
        status="awaiting_budget_reservation",
        recorded_by="native_job_service",
        recorded_by_oid=20001,
        request_login="original_request_service",
        request_login_oid=20002,
        recorded_at="2026-10-24T10:00:00.000000Z",
    )
    return {"document": d, "digest": digest(d)}


def test_closed_job_retains_all_native_slots_and_no_execution_grants():
    value = sample()
    record = jobs._record(value)
    assert record.metadata == value
    value["document"]["rule_ids"].clear()
    assert len(record.metadata["document"]["slots"]) == 6


@pytest.mark.parametrize("field", sorted(jobs.FALSE_FIELDS))
def test_rehashing_a_grant_cannot_authorize_execution_or_funds(field):
    value = sample()
    d = value["document"]
    d[field] = True
    value["digest"] = digest(d)
    with pytest.raises(jobs.JudgmentJobError):
        jobs._record(value)


@pytest.mark.parametrize(
    "mutation",
    [
        "drop_slot",
        "duplicate_slot_id",
        "reorder_rules",
        "slot_bool",
        "attempt_bool",
        "wrong_rule",
        "partial_calls",
        "extra_body",
        "budget_string",
        "budget_insufficient",
        "generation_bool",
        "oid_bool",
    ],
)
def test_partial_or_malformed_jobs_cannot_masquerade_as_complete(mutation):
    value = sample()
    d = value["document"]
    if mutation == "drop_slot":
        d["slots"].pop()
    elif mutation == "duplicate_slot_id":
        d["slots"][1]["slot_id"] = d["slots"][0]["slot_id"]
    elif mutation == "reorder_rules":
        d["rule_ids"].reverse()
    elif mutation == "slot_bool":
        d["slots"][0]["slot_number"] = True
    elif mutation == "attempt_bool":
        d["max_attempts_per_slot"] = True
    elif mutation == "wrong_rule":
        d["slots"][0]["rule_id"] = str(uuid4())
    elif mutation == "partial_calls":
        d["maximum_external_calls"] = 1
    elif mutation == "extra_body":
        d["body"] = "forbidden raw body"
    elif mutation == "budget_string":
        d["budget_ceiling_minor"] = "500"
    elif mutation == "budget_insufficient":
        d["budget_ceiling_minor"] = 0
    elif mutation == "generation_bool":
        d["generation"] = True
    elif mutation == "oid_bool":
        d["request_login_oid"] = True
    value["digest"] = digest(d)
    with pytest.raises(jobs.JudgmentJobError):
        jobs._record(value)


def test_evidence_revision_is_contiguous_and_does_not_rewrite_job():
    job = sample()
    d = {
        "version": "material-judgment-evidence/1",
        "event_id": str(uuid4()),
        "job_id": job["document"]["job_id"],
        "job_digest": job["digest"],
        "command_id": str(uuid4()),
        "revision": 2,
        "previous_revision": 1,
        "renewal_id": str(uuid4()),
        "renewal_digest": "b" * 64,
        "recorded_at": "2026-10-24T10:00:00.000000Z",
        "recorded_by": "native_job_service",
        "recorded_by_oid": 20001,
    }
    value = {"document": d, "digest": digest(d)}
    record = jobs._event(value)
    broken = deepcopy(value)
    broken["document"]["previous_revision"] = 0
    broken["digest"] = digest(broken["document"])
    with pytest.raises(jobs.JudgmentJobError):
        jobs._event(broken)
    assert record.metadata == value and job["document"]["generation"] == 1
