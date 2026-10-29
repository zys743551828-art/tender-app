"""Durable refusal orchestration, simulated ledger; no native or paid acceptance."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from packages.contracts import package_material_execution_api as contracts
from packages.domain.runtime import DomainError, sha
from packages.model_governance import package_material_execution_check as checks

ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "apps/web/src/test-fixtures/technical-execution-http.json").read_text())


@pytest.fixture
def world(monkeypatch):
    saved = SOURCE["scope"]
    s = saved["manifest"]["preview"]["manifest"]["scope"]
    scope = tuple(s[k] for k in ("bid_id", "package_id", "revision_id"))
    qualification = deepcopy(SOURCE["context"]["qualification"])
    monkeypatch.setattr(
        checks.eligibility, "scoring_context", lambda *_a: (deepcopy(qualification), "unused")
    )
    ledger, audits = {}, []

    class Command:
        def __init__(self, c, actor, kind, target, key, request, condition):
            if not key:
                raise DomainError("IDEMPOTENCY_REQUIRED", "required", 428)
            self.key = (actor, kind, target, key)
            self.digest = sha({"request": request, "condition": condition})
            existing = ledger.get(self.key)
            if existing and existing[0] != self.digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "conflict", 409)
            self.id = existing[2] if existing else uuid4()
            self.replay = deepcopy(existing[1]) if existing else None

        def finish(self, body, status=200, headers=None):
            result = {"body": body, "status": status, "headers": headers or {}}
            ledger[self.key] = (self.digest, deepcopy(result), self.id)
            return result

    monkeypatch.setattr(checks, "Command", Command)
    monkeypatch.setattr(checks, "audit", lambda *_a: audits.append(1))
    context, tag = checks.context(None, scope, saved["manifest"]["id"])
    body = {
        "version": "package-material-execution-check/1",
        "scope_digest": saved["digest"],
        **{k: v for k, v in context["target"].items() if k != "profile"},
        "input_reference": None,
        "budget_usd": "0",
    }
    return {
        "saved": saved,
        "scope": scope,
        "actor": str(uuid4()),
        "context": context,
        "tag": tag,
        "body": body,
        "ledger": ledger,
        "audits": audits,
        "qualification": qualification,
    }


def call(w, **overrides):
    args = (
        dict(
            c=None,
            scope=w["scope"],
            scope_id=w["saved"]["manifest"]["id"],
            actor=w["actor"],
            body=w["body"],
            condition=w["tag"],
            key="original",
        )
        | overrides
    )
    return checks.check(**args)


def test_refusal_replays_after_source_change_without_new_tasks_or_new_audit(world):
    w = world
    result, replay = call(w)
    assert not replay and result["body"]["state"] == "blocked"
    contracts.validate("PackageMaterialExecutionReceipt", result["body"])
    w["qualification"]["observed_at"] = "2026-10-27T00:00:00Z"
    assert call(w) == (result, True)
    assert len(w["ledger"]) == 1 and len(w["audits"]) == 1
    assert not result["body"]["fee_reserved"] and result["body"]["model_requests"] == 0


@pytest.mark.parametrize(
    "field", ["profile_digest", "serializer_digest", "judgment_method_digest", "scope_digest"]
)
def test_drift_does_not_record_new_receipt(world, field):
    with pytest.raises(DomainError):
        call(world, body=world["body"] | {field: "a" * 64})
    assert not world["ledger"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("budget_usd", "unknown"),
        ("budget_usd", "-1"),
        ("budget_usd", "NaN"),
        ("execution_authorized", True),
        ("input_reference", {"seal_id": str(uuid4())}),
    ],
)
def test_unknown_cost_or_extra_grant_rejected(world, field, value):
    with pytest.raises(DomainError, match="协议"):
        call(world, body=world["body"] | {field: value})
    assert not world["ledger"]


def test_complete_client_reference_is_recorded_but_never_authority(world):
    reference = {
        "seal_id": str(uuid4()),
        "seal_digest": "a" * 64,
        "input_digest": "b" * 64,
        "quote_id": str(uuid4()),
        "quote_digest": "c" * 64,
    }
    result, _ = call(
        world, body=world["body"] | {"input_reference": reference, "budget_usd": "120.50"}
    )
    assert (
        result["body"]["reference_status"] == "unverified"
        and not result["body"]["execution_authorized"]
    )


def test_changed_same_key_is_conflict_and_actor_isolation(world):
    first, _ = call(world)
    with pytest.raises(DomainError, match="conflict"):
        call(world, body=world["body"] | {"budget_usd": "1"})
    other, _ = call(world, actor=str(uuid4()))
    assert other["body"]["command_id"] != first["body"]["command_id"]


@pytest.mark.parametrize(
    "condition,key,status", [(None, "key", 428), ("stale", "key", 412), ("unused", None, 428)]
)
def test_preconditions_remain_closed(world, condition, key, status):
    with pytest.raises(DomainError) as e:
        call(world, condition=condition, key=key)
    assert e.value.status == status
    assert not world["ledger"]


def test_scope_permission_failure_precedes_ledger(world, monkeypatch):
    def denied(*_a):
        raise DomainError("NOT_FOUND", "scope unavailable", 404)

    monkeypatch.setattr(checks.eligibility, "scoring_context", denied)
    with pytest.raises(DomainError):
        call(world)
    assert not world["ledger"]


def test_shared_frontend_fixture_is_exact_current_protocol(world):
    fixture = json.loads(
        (ROOT / "apps/web/src/test-fixtures/material-execution-check.json").read_text()
    )
    assert (
        fixture["context"] == world["context"]
        and fixture["etag"] == world["tag"]
        and fixture["request"] == world["body"]
    )
    contracts.validate("PackageMaterialExecutionReceipt", fixture["receipt"])


@pytest.mark.parametrize("code", ["SOURCE_EXPIRED", "SOURCE_REVOKED"])
def test_changed_source_blocks_old_condition_and_is_retained_in_new_refusal(world, code):
    world["qualification"]["blockers"].append(checks.reason(code, "Current source unavailable"))
    with pytest.raises(DomainError) as error:
        call(world)
    assert error.value.status == 412 and not world["ledger"]
    _, tag = checks.context(None, world["scope"], world["saved"]["manifest"]["id"])
    result, _ = call(world, condition=tag)
    assert code in {g["code"] for g in result["body"]["blockers"]}
    assert result["body"]["state"] == "blocked"
