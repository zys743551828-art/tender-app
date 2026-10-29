"""Simulated persistence orchestration, not native concurrency/rollback proof."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_material_qualification import document

from packages.domain.errors import DomainError
from packages.domain.runtime import sha
from packages.model_governance import material_qualification_registry as r


@pytest.fixture
def registry(monkeypatch):
    record_id, scope_id, actor = map(str, (uuid4(), uuid4(), uuid4()))
    row = {
        "id": record_id,
        "scope_id": scope_id,
        "digest": "a" * 64,
        "document": document(),
        "created_by": actor,
        "created_at": "2026-10-24T00:00:00Z",
        "revision": 0,
        "decision": None,
        "reviewer_id": None,
        "reason": None,
        "reviewed_at": None,
    }
    ledger, events = {}, []
    at = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(r, "_scope", lambda *_: {})
    monkeypatch.setattr(r, "_now", lambda *_: at)
    monkeypatch.setattr(r, "_evidence", lambda *_: None)
    monkeypatch.setattr(r, "audit", lambda *args: events.append(args))

    def read(_c, scope, identity, **_):
        if scope != scope_id or identity != record_id:
            raise DomainError("NOT_FOUND", "scope", 404)
        return deepcopy(row)

    monkeypatch.setattr(r, "_row", read)

    class Command:
        def __init__(self, c, who, kind, target, key, body, condition=None):
            self.id = uuid4()
            self.key = (who, kind, target, key)
            self.digest = sha({"body": body, "condition": condition})
            previous = ledger.get(self.key)
            if previous and previous[0] != self.digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "conflict", 409)
            self.replay = deepcopy(previous[1]) if previous else None

        def finish(self, body, status=200, headers=None):
            result = {"body": deepcopy(body), "status": status, "headers": headers or {}}
            ledger[self.key] = self.digest, result
            return result

    monkeypatch.setattr(r, "Command", Command)

    class Connection:
        def execute(self, sql, params):
            if sql.startswith("INSERT INTO material_qualification.decisions"):
                _, _, revision, decision, reviewer, reason = params
                row.update(
                    revision=revision,
                    decision=decision,
                    reviewer_id=reviewer,
                    reason=reason,
                    reviewed_at=at,
                )
            elif not sql.startswith("UPDATE material_qualification.heads"):
                raise AssertionError(sql)

    def apply(decision="approved", revision=0, key="first", **changes):
        args = dict(
            c=Connection(),
            scope=("bid", "package", "revision"),
            scope_id=scope_id,
            record_id=record_id,
            actor=actor,
            body={"decision": decision, "reason": "Synthetic review"},
            condition=r.etag("material-qualification", record_id, revision),
            key=key,
        )
        return r.review(**(args | changes))

    return apply, row, ledger, events


def test_lost_ack_replays_historical_approval_after_revocation(registry):
    apply, row, ledger, events = registry
    approval, replay = apply()
    assert not replay and approval["body"]["state"] == "approved"
    apply("revoked", 1, "withdraw")
    repeated, replay = apply()
    assert replay and repeated == approval and row["decision"] == "revoked"
    assert len(ledger) == len(events) == 2
    assert repeated["body"]["execution_authorized"] is False


def test_stale_etag_and_changed_key_do_not_change_head(registry):
    apply, row, _, events = registry
    apply()
    for kwargs, code in [
        ({"decision": "revoked", "key": "fresh"}, "REVISION_CONFLICT"),
        ({"decision": "revoked"}, "IDEMPOTENCY_CONFLICT"),
    ]:
        with pytest.raises(DomainError) as failure:
            apply(**kwargs)
        assert failure.value.code == code
    assert row["revision"] == 1 and len(events) == 1


def test_evidence_failure_does_not_publish_decision(registry, monkeypatch):
    apply, row, ledger, events = registry

    def changed(*_):
        raise DomainError("EVIDENCE_CHANGED", "changed")

    monkeypatch.setattr(r, "_evidence", changed)
    with pytest.raises(DomainError):
        apply()
    assert row["revision"] == 0 and not ledger and not events


def test_wrong_scope_fails_before_command(registry):
    apply, row, ledger, events = registry
    with pytest.raises(DomainError) as failure:
        apply(scope_id=str(uuid4()))
    assert failure.value.status == 404
    assert row["revision"] == 0 and not ledger and not events
