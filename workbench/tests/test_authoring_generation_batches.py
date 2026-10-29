"""Exact integer budgets, bounded request contracts and immutable command bindings."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.assistant import generation_batch_contracts as contracts
from packages.assistant import generation_batches as service
from packages.domain.runtime import DomainError, now, sha


def price():
    return {
        "input_upper": 2097152,
        "output_upper": 8192,
        "input_per_million_minor": 14000000,
        "output_per_million_minor": 28000000,
    }


def body():
    return {
        "base_draft_revision": 1,
        "price_version_id": str(uuid4()),
        "currency": "USD",
        "amount_scale": 1000000000,
        "total_limit_minor": 100000000,
        "sections": [
            {
                "section_id": str(uuid4()),
                "base_section_revision": 1,
                "instruction": "按实际来源完善本章",
                "source_version_ids": [],
                "selected_node_ids": ["legacy paragraph 1"],
                "max_tokens": 2048,
                "budget_limit_minor": 100000000,
            }
        ],
        "reason": "明确确认累计预算",
    }


def record(state, reserve=100, charge=None, *, unknown=False, manual=False):
    return {
        "currency": "USD",
        "budget_state": state,
        "reserved_minor": reserve,
        "charged_minor": charge,
        "unresolved_call": unknown,
        "requires_manual_reconciliation": manual,
    }


def test_exact_total_budget_keeps_settled_previous_attempts_and_all_unresolved_holds():
    result = service.budget_view(
        [
            record("settled", charge=7),
            record("released", charge=0),
            record("held"),
            record("sent"),
            record("unknown"),
        ],
        400,
        "USD",
    )
    assert result["charged_minor"] == 7 and result["reserved_minor"] == 300
    assert result["exposure_minor"] == 307 and result["remaining_minor"] == 93
    assert result["requires_reconciliation"] and not result["over_limit"]
    reopened = service.budget_view([record("unknown"), record("settled", charge=10)], 100, "USD")
    assert reopened["over_limit"] and reopened["remaining_minor"] == 0


@pytest.mark.parametrize("value", [-1, True, 1.2, 9007199254740992, None])
def test_money_never_rounds_or_treats_boolean_as_amount(value):
    with pytest.raises(DomainError, match="整数范围"):
        service.amount(value)


def test_total_sum_rejects_unsafe_json_integer_even_when_each_ledger_value_is_safe():
    with pytest.raises(DomainError) as exc:
        service.budget_view(
            [record("held", reserve=contracts.MAX_MINOR), record("settled", charge=1)],
            contracts.MAX_MINOR,
            "USD",
        )
    assert exc.value.code == "AUTHORING_GENERATION_BATCH_AMOUNT_UNREPRESENTABLE"


def test_actual_reservation_estimate_uses_integer_ceiling_once_after_summing_costs():
    p = price()
    assert service.reservation_estimate(p, 2048) == 29417472
    p.update(input_upper=1, input_per_million_minor=1, output_per_million_minor=1)
    assert service.reservation_estimate(p, 1) == 1
    with pytest.raises(DomainError):
        service.reservation_estimate(p, 8193)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(total_limit_minor=contracts.MAX_MINOR + 1),
        lambda v: v.update(total_limit_minor=True),
        lambda v: v.update(amount_scale=100),
        lambda v: v["sections"][0].update(selected_node_ids=[]),
        lambda v: v["sections"][0].update(selected_node_ids=["x" * 129]),
        lambda v: v["sections"][0].update(instruction="x\x00y"),
        lambda v: v["sections"][0].update(instruction="x\ud800y"),
        lambda v: v["sections"][0].update(source_version_ids=[str(uuid4())] * 2),
        lambda v: v["sections"][0].update(max_tokens=8193),
    ],
)
def test_request_rejects_unsafe_budgets_hidden_characters_and_unbounded_scope(mutate):
    value = body()
    mutate(value)
    with pytest.raises(DomainError):
        contracts.validate("AuthoringGenerationBatchCreateRequest", value)


def test_non_uuid_existing_node_id_and_exact_maximum_are_valid():
    value = body()
    value["total_limit_minor"] = contracts.MAX_MINOR
    contracts.validate("AuthoringGenerationBatchCreateRequest", value)


def test_command_ack_binds_scope_exact_body_actor_key_and_original_if_match():
    request = body()
    actor, bid, draft, command = [uuid4() for _ in range(4)]
    value = service.binding(
        SimpleNamespace(id=command), actor, "original-key", request, '"original-tag"', bid, draft
    )
    assert value["request_digest"] == sha(
        {
            "body": {"bid_id": str(bid), "draft_id": str(draft), **request},
            "if_match": '"original-tag"',
        }
    )
    original = deepcopy(value)
    request["reason"] = "changed afterwards"
    assert (
        value == original
        and value["actor_id"] == str(actor)
        and value["command_id"] == str(command)
    )


def test_frozen_byte_limit_queries_actual_job_manifests_and_includes_retries():
    captured = []

    class Connection:
        def execute(self, query, args):
            captured.append((query, args))
            return self

        def fetchone(self):
            return {"size": contracts.MAX_FROZEN_BYTES + 1}

    with pytest.raises(DomainError) as exc:
        service.assert_frozen_size(Connection(), uuid4())
    assert exc.value.code == "AUTHORING_GENERATION_BATCH_TOO_LARGE"
    assert "j.input_manifest" in captured[0][0] and "attempt=1" not in captured[0][0]


def test_history_projection_does_not_fetch_request_sections_or_complete_manifest():
    captured = []

    class Connection:
        def execute(self, query, args=()):
            captured.append(query)
            self.query = query
            return self

        def fetchone(self):
            return {"id": uuid4()}

        def fetchall(self):
            return []

    from unittest.mock import patch

    with patch.object(service, "require_schema"):
        assert service.history(Connection(), uuid4(), uuid4())["items"] == []
    projection = next(q for q in captured if "assistant_generation_batches b" in q)
    assert "jsonb_array_length(b.manifest->'sections')" in projection
    assert "b.manifest->'request'->'sections'" not in projection
    assert "b.*" not in projection and "b.manifest," not in projection


def test_processing_count_includes_paid_success_waiting_for_candidate_publication():
    row = {
        "id": uuid4(),
        "bid_id": uuid4(),
        "draft_id": uuid4(),
        "digest": "a" * 64,
        "base_draft_revision": 1,
        "created_at": now(),
        "created_by": uuid4(),
        "resolution": None,
        "manifest": {
            "section_count": 1,
            "request": {"total_limit_minor": 100},
            "price": {"currency": "USD"},
        },
    }
    item = record("settled", charge=3) | {
        "section_id": uuid4(),
        "state": "succeeded",
        "publication_state": "pending",
        "action_state": None,
        "expires_at": now() + timedelta(hours=1),
    }
    result = service.summary(row, [item])
    assert result["running_count"] == 1 and result["ready_count"] == 0
