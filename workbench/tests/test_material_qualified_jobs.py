"""Synthetic API/native-boundary orchestration; not a native transaction proof."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_material_qualification import document

from apps.api import package_technical_execution as routes
from packages.domain.errors import DomainError
from packages.domain.runtime import sha
from packages.model_governance import material_qualification_guard as guard
from packages.model_governance import material_qualification_registry as registry
from packages.model_governance import material_qualified_job_transport as transport
from packages.model_governance import material_qualified_jobs as q


@pytest.fixture
def world(monkeypatch):
    actor, bid, scope_id, qualification_id = [str(uuid4()) for _ in range(4)]
    doc = document()
    row = {
        "id": qualification_id,
        "bid_id": bid,
        "scope_id": scope_id,
        "document": doc,
        "digest": sha(doc),
        "revision": 1,
        "decision": "approved",
        "reviewer_id": actor,
    }
    body = {
        "version": q.VERSION,
        "scope_digest": doc["binding"]["scope_digest"],
        "qualification_id": qualification_id,
        "qualification_digest": row["digest"],
        "qualification_revision": 1,
        "renewal_id": str(uuid4()),
        "renewal_digest": "e" * 64,
    }
    intents, accepted, ledger, audit = {}, {}, {}, []
    state = {"depth": 0, "submits": 0}
    monkeypatch.setattr(registry, "_scope", lambda *_: {"digest": body["scope_digest"]})
    monkeypatch.setattr(registry, "_row", lambda *_a, **_k: deepcopy(row))
    monkeypatch.setattr(registry, "_evidence", lambda *_: None)
    monkeypatch.setattr(
        registry, "_now", lambda *_: datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    )
    monkeypatch.setattr(guard, "audit", lambda *_: None)
    monkeypatch.setattr(q, "audit", lambda *a: audit.append(a))

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return deepcopy(self.value)

    class Connection:
        def execute(self, sql, params):
            if sql.startswith("SELECT active"):
                return Result({"active": True})
            if sql.startswith("INSERT INTO material_qualification.intents"):
                keys = (
                    "id",
                    "actor_id",
                    "bid_id",
                    "scope_id",
                    "qualification_id",
                    "qualification_digest",
                    "qualification_revision",
                    "document",
                    "digest",
                )
                value = dict(zip(keys, params, strict=True))
                value["id"] = str(value["id"])
                value["document"] = deepcopy(value["document"].obj)
                intents[value["id"]] = value
                return Result(None)
            if sql.startswith("SELECT * FROM material_qualification.intents"):
                value = intents.get(str(params[0]))
                return Result(
                    value
                    if value
                    and (value["scope_id"], value["actor_id"], value["bid_id"]) == params[1:]
                    else None
                )
            if sql.startswith("SELECT * FROM material_qualification.acceptances"):
                return Result(accepted.get(str(params[0])))
            raise AssertionError(sql)

    class Command:
        def __init__(self, c, actor, kind, target, key, request, condition):
            self.slot = actor, kind, target, key
            self.digest = sha({"request": request, "condition": condition})
            old = ledger.get(self.slot)
            if old and old[0] != self.digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "changed", 409)
            self.id = old[1] if old else uuid4()
            self.replay = deepcopy(old[2]) if old else None

        def finish(self, body, status=200):
            result = {"body": body, "status": status, "headers": {}}
            ledger[self.slot] = self.digest, self.id, result
            return result

    monkeypatch.setattr(q, "Command", Command)
    connection = Connection()

    @contextmanager
    def connect():
        state["depth"] += 1
        try:
            yield connection
        finally:
            state["depth"] -= 1

    monkeypatch.setattr(routes, "connection", connect)
    scope = (bid, str(uuid4()), str(uuid4()))

    def prepare(**changes):
        args = dict(
            c=connection,
            scope=scope,
            scope_id=scope_id,
            actor=actor,
            body=deepcopy(body),
            condition=f'"material-qualification:{qualification_id}:1"',
            key="original",
        )
        return q.prepare(**(args | changes))

    def commit(command):
        assert state["depth"] == 0
        state["submits"] += 1
        identity = command["arguments"]["command_id"]
        data = {
            "job_id": str(uuid4()),
            "command_id": identity,
            "bid_id": bid,
            "scope_id": scope_id,
            "generation": 1,
        }
        accepted[identity] = {"job_id": data["job_id"], "job_digest": sha(data), "document": data}
        return "unconfirmed"  # Native commit followed by lost CLI ACK.

    monkeypatch.setattr(transport, "submit", commit)
    return {
        "prepare": prepare,
        "resume": lambda identity, who=actor: routes._qualified_resume(
            scope, scope_id, who, identity
        ),
        "row": row,
        "body": body,
        "intents": intents,
        "accepted": accepted,
        "state": state,
        "audit": audit,
    }


def test_commit_after_intent_transaction_and_lost_ack_recovers_without_new_send(world):
    identity = world["prepare"]()
    assert world["prepare"]() == identity and len(world["intents"]) == len(world["audit"]) == 1
    value = world["resume"](identity)
    assert value["state"] == "accepted_preparation" and not value["send_authorized"]
    assert value["fee_state"] == "not_observed" and not value["accuracy_verified"]
    world["row"].update(revision=2, decision="revoked")
    assert world["resume"](identity) == value and world["state"]["submits"] == 1


def test_changed_same_key_and_cross_member_rejected(world):
    identity = world["prepare"]()
    with pytest.raises(DomainError, match="changed"):
        world["prepare"](body=world["body"] | {"renewal_digest": "f" * 64})
    with pytest.raises(DomainError) as failure:
        world["resume"](identity, str(uuid4()))
    assert failure.value.status == 404 and world["state"]["submits"] == 0


def test_revocation_blocks_before_transport(world):
    identity = world["prepare"]()
    world["row"].update(revision=2, decision="revoked")
    value = world["resume"](identity)
    assert (
        value["state"] == "pending"
        and value["pending_reason"] == "MATERIAL_QUALIFICATION_NOT_CURRENT"
    )
    assert world["state"]["submits"] == 0


def test_cli_success_is_not_native_acceptance(world, monkeypatch):
    identity = world["prepare"]()
    monkeypatch.setattr(transport, "submit", lambda *_: "submitted")
    assert world["resume"](identity)["state"] == "pending"


def test_tampered_native_receipt_is_not_accepted(world):
    identity = world["prepare"]()
    world["resume"](identity)
    world["accepted"][identity]["document"]["scope_id"] = str(uuid4())
    with pytest.raises(DomainError):
        world["resume"](identity)


def test_guard_missing_cannot_create_intent(world, monkeypatch):
    def absent(*_):
        raise DomainError("GUARD_UNAVAILABLE", "guard unavailable", 503)

    monkeypatch.setattr(guard, "audit", absent)
    with pytest.raises(DomainError):
        world["prepare"]()
    assert not world["intents"] and world["state"]["submits"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("qualification_revision", True),
        ("qualification_digest", "bad"),
        ("renewal_id", "bad"),
        ("execution_authorized", True),
    ],
)
def test_closed_request(world, field, value):
    with pytest.raises(DomainError):
        world["prepare"](body=world["body"] | {field: value})
    assert not world["intents"]


def test_guard_version_drift_does_not_reinterpret_old_intent(world):
    identity = world["prepare"]()
    frozen = world["intents"][identity]
    frozen["document"]["guard_digest"] = "f" * 64
    frozen["digest"] = sha(frozen["document"])
    value = world["resume"](identity)
    assert (
        value["state"] == "pending"
        and value["pending_reason"] == "MATERIAL_QUALIFICATION_GUARD_CHANGED"
    )
    assert world["state"]["submits"] == 0
