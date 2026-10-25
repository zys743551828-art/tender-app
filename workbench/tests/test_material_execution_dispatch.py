"""Closed Kafka protocol, durable ACK ordering and pre-budget live admission."""

import asyncio
import importlib.util
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from psycopg.pq import TransactionStatus

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_execution_dispatch as dispatch
from packages.model_governance import material_execution_runtime as runtime


def uid():
    return str(uuid4())


def event():
    return {
        "version": "material-judgment-task/1",
        "event_id": uid(),
        "job_id": uid(),
        "generation": 1,
    }


def envelope(value):
    return {"document": deepcopy(value), "digest": digest(value)}


def idle():
    return SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))


def observation(*, purpose="worker", mode="production_admission", state="running", new=True):
    now = datetime.now(timezone.utc)
    message = event()
    d = {
        "version": "material-dispatch-lease/1",
        "lease_id": uid(),
        "command_id": uid(),
        "event_id": message["event_id"],
        "job_id": message["job_id"],
        "job_digest": digest("job"),
        "generation": 1,
        "fence": 1,
        "profile_id": uid(),
        "profile_digest": digest("profile"),
        "profile_head_revision": 1,
        "purpose": purpose,
        "mode": mode,
        "origin": "synthetic_mechanism",
        "token": uid(),
        "lease_until": (now + timedelta(seconds=120)).isoformat(),
        "message": message,
        "dispatch_method_digest": dispatch.method_digest(),
        "native_sql_method_digest": digest("sql"),
        "recorded_by": "synthetic_" + purpose,
        "recorded_by_oid": 9001,
        "recorded_at": now.isoformat(),
        **dict.fromkeys(dispatch.FALSE_FIELDS, False),
    }
    value = {
        "lease": envelope(d),
        "new_claim": new,
        "state": state,
        "lease_current": state == "running",
        "lease_until": d["lease_until"],
        "result": None,
    }
    if state in dispatch.TERMINAL:
        result = {
            key: d[key]
            for key in (
                "event_id",
                "job_id",
                "generation",
                "job_digest",
                "profile_id",
                "profile_digest",
                "dispatch_method_digest",
                "mode",
                "recorded_by",
                "recorded_by_oid",
                "recorded_at",
            )
        }
        result |= {
            "version": "material-dispatch-result/1",
            "state": state,
            "source_current": True,
            "financial_state": "unknown"
            if state == "billing_unresolved"
            else "completed"
            if state == "mechanism_completed"
            else None,
            "held_minor": 45 if state == "billing_unresolved" else 0,
            "estimated_minor": 0,
            "observed_send_grants": 1 if state == "billing_unresolved" else 0,
            "failure_code": "LIVE_QUALIFICATION_UNAVAILABLE",
            "preparation_fenced": False,
            "blockers": list(dispatch.BLOCKERS) if mode == "production_admission" else [],
            **dict.fromkeys(dispatch.FALSE_FIELDS, False),
        }
        value["result"] = envelope(result)
    return dispatch._observation(value, purpose)


def test_id_only_protocol_is_canonical_and_private_receipt_repr_is_safe():
    source = event()
    assert dispatch.message(canonical(source)) == source
    record = observation()
    assert "token" not in repr(record) and record.metadata["lease"]["document"][
        "token"
    ] not in repr(record)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"null",
        b"[]",
        b"x" * 1025,
        b'{"version":1,"version":2}',
        b"\xff",
        b'{"generation":NaN}',
    ],
)
def test_malformed_messages_never_reach_a_database(raw):
    with pytest.raises(dispatch.MaterialDispatchError):
        dispatch.message(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", True),
        ("generation", 1.0),
        ("generation", 2),
        ("event_id", "../private"),
        ("job_id", "A" * 36),
        ("version", "task-envelope/1"),
        ("body", "not permitted"),
    ],
)
def test_message_fields_are_closed_and_generation_is_an_integer(field, value):
    m = event() | {field: value}
    with pytest.raises(dispatch.MaterialDispatchError):
        dispatch.message(m)


def test_returned_qualification_escalation_is_rejected():
    valid = observation().metadata
    changed = deepcopy(valid)
    changed["lease"]["document"]["production_send_authorized"] = True
    changed["lease"]["digest"] = digest(changed["lease"]["document"])
    with pytest.raises(dispatch.MaterialDispatchError, match="NATIVE_RESULT_INVALID"):
        dispatch._observation(changed, "worker")
    changed = observation(state="billing_unresolved", new=False).metadata
    changed["result"]["document"]["financial_state"] = None
    changed["result"]["digest"] = digest(changed["result"]["document"])
    with pytest.raises(dispatch.MaterialDispatchError, match="NATIVE_RESULT_INVALID"):
        dispatch._observation(changed, "worker")


def test_production_admission_runs_before_any_reader_budget_or_fixture(monkeypatch):
    calls = []
    record = observation()
    monkeypatch.setattr(dispatch, "claim_delivery", lambda *a, **k: record)
    original = execution.execute_attempt

    def admit(*a, **k):
        calls.append("admission")
        return original(*a, **k)

    def forbidden(*a, **k):
        pytest.fail("production path opened a reader or attempted a reservation")

    def finish(c, value, **kwargs):
        assert calls == ["admission"]
        assert kwargs["failure"] == "LIVE_QUALIFICATION_UNAVAILABLE"
        calls.append("durable_result")
        return observation(state="blocked", new=False)

    monkeypatch.setattr(execution, "execute_attempt", admit)
    monkeypatch.setattr(dispatch, "owned_job", forbidden)
    monkeypatch.setattr(execution, "begin_attempt", forbidden)
    monkeypatch.setattr(runtime, "_validate_ports", forbidden)
    monkeypatch.setattr(dispatch, "finish", finish)
    result = asyncio.run(
        runtime.deliver(
            idle(),
            event(),
            expected_method_digest=dispatch.method_digest(),
            mechanism_ports=object(),
        )
    )
    assert result.acknowledge and calls == ["admission", "durable_result"]


@pytest.mark.parametrize(
    "state,new,ack",
    [("blocked", False, True), ("billing_unresolved", False, True), ("running", False, False)],
)
def test_terminal_duplicate_and_busy_delivery_never_reenter_admission(monkeypatch, state, new, ack):
    record = observation(state=state, new=new)
    monkeypatch.setattr(dispatch, "claim_delivery", lambda *a, **k: record)

    def forbidden(*a, **k):
        pytest.fail("duplicate reentered execution")

    monkeypatch.setattr(runtime, "production_admission", forbidden)
    monkeypatch.setattr(dispatch, "owned_job", forbidden)
    result = asyncio.run(
        runtime.deliver(idle(), event(), expected_method_digest=dispatch.method_digest())
    )
    assert result.acknowledge is ack


@pytest.mark.parametrize(
    "financial",
    ["unknown", "in_flight", "paused_invalid", "paused_stale", "paused_overrun", "completed"],
)
def test_previous_financial_state_stops_before_recovery_or_new_send(monkeypatch, financial):
    record = observation(mode="synthetic_mechanism")
    connections = [idle() for _ in range(7)]
    ports = runtime.MechanismPorts(
        *connections[1:], "development_s3", lambda v: None, httpx.MockTransport(lambda r: None)
    )
    monkeypatch.setattr(dispatch, "claim_delivery", lambda *a, **k: record)
    monkeypatch.setattr(
        dispatch,
        "owned_job",
        lambda *a, **k: dispatch.OwnedJob({"financial_state": financial, "source_current": True}),
    )
    monkeypatch.setattr(
        dispatch,
        "finish",
        lambda *a, **k: observation(
            mode="synthetic_mechanism",
            state="billing_unresolved" if financial in {"unknown", "in_flight"} else "blocked",
            new=False,
        ),
    )

    def forbidden(*a, **k):
        pytest.fail("unresolved financial state reached preparation")

    monkeypatch.setattr(runtime.preparation, "claim", forbidden)
    result = asyncio.run(
        runtime.deliver(
            connections[0],
            event(),
            expected_method_digest=dispatch.method_digest(),
            mechanism_ports=ports,
        )
    )
    assert result.acknowledge


def test_mechanism_transport_cannot_be_a_network_client_or_subclass():
    connections = [idle() for _ in range(7)]

    class Fake(httpx.MockTransport):
        pass

    for transport in (object(), Fake(lambda r: None)):
        ports = runtime.MechanismPorts(
            *connections[1:], "development_s3", lambda v: None, transport
        )
        with pytest.raises(dispatch.MaterialDispatchError, match="ISOLATED_TRANSPORT_REQUIRED"):
            runtime._validate_ports(connections[0], ports)


class Producer:
    def __init__(self, confirmed=True):
        self.sent = []
        self.confirmed = confirmed

    def produce(self, topic, **kwargs):
        self.sent.append((topic, kwargs))

    def poll(self, timeout):
        self.sent[0][1]["on_delivery"](None if self.confirmed else "broker failure", None)


@pytest.mark.parametrize("confirmed", [True, False])
def test_relay_commits_native_ack_only_after_broker_confirmation(monkeypatch, confirmed):
    record = observation(purpose="relay")
    broker = Producer(confirmed)
    monkeypatch.setattr(dispatch, "claim_publication", lambda *a, **k: record)
    acks = []
    monkeypatch.setattr(dispatch, "ack_publication", lambda *a, **k: acks.append(a))
    args = {
        "profile_id": uid(),
        "expected_profile_digest": digest("p"),
        "expected_method_digest": dispatch.method_digest(),
    }
    if confirmed:
        runtime.relay_once(idle(), broker, **args)
        assert len(acks) == 1
    else:
        with pytest.raises(dispatch.MaterialDispatchError, match="PUBLICATION_UNCONFIRMED"):
            runtime.relay_once(idle(), broker, **args)
        assert not acks
    topic, sent = broker.sent[0]
    m = dispatch.message(sent["value"])
    assert topic == runtime.TOPIC and sent["key"] == m["job_id"].encode("ascii")
    assert set(m) == {"version", "event_id", "job_id", "generation"}


class Message:
    def __init__(self, m=None):
        self.m = event() if m is None else m

    def error(self):
        return None

    def value(self):
        return canonical(self.m)

    def key(self):
        return self.m["job_id"].encode("ascii")

    def topic(self):
        return runtime.TOPIC

    def headers(self):
        return None

    def partition(self):
        return 0

    def offset(self):
        return 7


class Consumer:
    def __init__(self, item, *, commit_error=False):
        self.item, self.commit_error = item, commit_error
        self.commits, self.seeks = [], []

    def poll(self, timeout):
        return self.item

    def commit(self, **kwargs):
        self.commits.append(kwargs)
        if self.commit_error:
            raise ValueError("private broker details must not escape")
        return [
            SimpleNamespace(
                error=None,
                topic=self.item.topic(),
                partition=self.item.partition(),
                offset=self.item.offset() + 1,
            )
        ]

    def seek(self, position):
        self.seeks.append(position.offset)


@pytest.mark.parametrize("ack", [True, False])
def test_consumer_commits_only_durable_terminal_and_rewinds_busy(monkeypatch, ack):
    broker = Consumer(Message())

    async def deliver(*a, **k):
        assert not broker.commits
        return runtime.DeliveryResult(
            observation(state="blocked" if ack else "running", new=False), ack
        )

    monkeypatch.setattr(runtime, "deliver", deliver)
    runtime.consume_once(idle(), broker, expected_method_digest=dispatch.method_digest())
    assert len(broker.commits) == int(ack)
    assert broker.seeks == ([] if ack else [7])


def test_offset_ack_loss_rewinds_without_leaking_private_errors(monkeypatch):
    broker = Consumer(Message(), commit_error=True)

    async def deliver(*a, **k):
        return runtime.DeliveryResult(observation(state="blocked", new=False), True)

    monkeypatch.setattr(runtime, "deliver", deliver)
    with pytest.raises(
        dispatch.MaterialDispatchError, match="^MATERIAL_DISPATCH_OFFSET_UNCONFIRMED$"
    ):
        runtime.consume_once(idle(), broker, expected_method_digest=dispatch.method_digest())
    assert broker.seeks == [7]


@pytest.mark.parametrize(
    "change",
    [{"error": "private-partition-error"}, {"offset": 9}, {"partition": 1}, {"topic": "other"}],
)
def test_partition_level_commit_errors_or_wrong_offsets_never_count_as_ack(monkeypatch, change):
    broker = Consumer(Message())

    async def deliver(*a, **k):
        return runtime.DeliveryResult(observation(state="blocked", new=False), True)

    monkeypatch.setattr(runtime, "deliver", deliver)
    row = {"error": None, "topic": runtime.TOPIC, "partition": 0, "offset": 8} | change
    monkeypatch.setattr(broker, "commit", lambda **k: [SimpleNamespace(**row)])
    with pytest.raises(
        dispatch.MaterialDispatchError, match="^MATERIAL_DISPATCH_OFFSET_UNCONFIRMED$"
    ):
        runtime.consume_once(idle(), broker, expected_method_digest=dispatch.method_digest())
    assert broker.seeks == [7]


def test_poison_message_is_rewound_and_never_committed():
    broker = Consumer(Message(event() | {"credential": "forbidden"}))
    with pytest.raises(dispatch.MaterialDispatchError, match="MESSAGE_INVALID"):
        runtime.consume_once(idle(), broker, expected_method_digest=dispatch.method_digest())
    assert broker.seeks == [7] and not broker.commits


def launcher():
    path = Path(__file__).parents[1] / "deploy/material_execution_worker.py"
    spec = importlib.util.spec_from_file_location("material_worker_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_launcher_allows_only_one_purpose_and_never_inherits_ambient_model(
    monkeypatch, tmp_path
):
    module = launcher()
    path = tmp_path / "worker.env"
    path.write_text(
        "MATERIAL_DISPATCH_DSN='synthetic-purpose-dsn'\nMATERIAL_DISPATCH_KAFKA_BOOTSTRAP='127.0.0.1:19092'\n"
    )
    path.chmod(0o600)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ambient-private-value")
    values = module.environment(path, "worker")
    assert set(values) == module.COMMON | {
        "WORKBENCH_ENV_FILE",
        "MATERIAL_DISPATCH_OWNED_PURPOSE",
        "LANG",
        "LC_ALL",
        "TZ",
    }
    assert "ambient-private-value" not in json.dumps(values)
    assert values["WORKBENCH_ENV_FILE"] == "/dev/null"
    path.write_text(path.read_text() + "MODEL_API_KEY=forbidden\n")
    with pytest.raises(ValueError, match="PROFILE_KEYS_INVALID"):
        module.environment(path, "worker")


@pytest.mark.parametrize("kind", ["public", "symlink", "duplicate"])
def test_launcher_rejects_nonprivate_or_ambiguous_configuration(tmp_path, kind):
    module = launcher()
    path = tmp_path / "config.env"
    path.write_text("MATERIAL_DISPATCH_DSN=x\nMATERIAL_DISPATCH_KAFKA_BOOTSTRAP=localhost:19092\n")
    path.chmod(0o600)
    if kind == "public":
        path.chmod(0o644)
    elif kind == "symlink":
        link = tmp_path / "link.env"
        link.symlink_to(path)
        path = link
    else:
        path.write_text(path.read_text() + "MATERIAL_DISPATCH_DSN=y\n")
    with pytest.raises(ValueError):
        module.environment(path, "worker")
