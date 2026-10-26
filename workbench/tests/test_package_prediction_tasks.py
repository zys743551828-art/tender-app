"""Durable lifecycle mechanisms with simulated authority; never actual qualification."""

# ruff: noqa: F401,F811
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from test_package_prediction import Authority, compute, setup
from test_package_prediction_reports import cohort, material, mirror, source

from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_model_live.producer import Executor
from packages.package_prediction_tasks import runtime, worker
from packages.package_prediction_tasks.application import HANDLER, Jobs


class Store:
    def __init__(self):
        self.values = {}
        self.hook = None

    def put(self, value):
        key = digest(value)
        self.values[key] = deepcopy(value)
        if self.hook:
            self.hook()
        return key

    def get(self, key):
        return deepcopy(self.values[key])


class Transactions(Authority):
    def __init__(self, packet):
        super().__init__(packet)
        self.record = None
        self.state = "queued"
        self.result = None
        self.published = False
        self.cancelled = False
        self.blocked = False
        self.commits = 0

    def __call__(self, body, publishing=None):
        @contextmanager
        def context():
            with super(Transactions, self).__call__() as tx:
                if publishing:
                    self.publishable(publishing)
                yield tx

        return context if publishing is not None else context()

    def job(self, body):
        if self.record and any(self.record["body"][k] != v for k, v in body.items()):
            raise GovernanceError("DENIED", "mismatch")
        return deepcopy(self.record)

    def view(self, job):
        state = (
            "stale"
            if self.published and self.revoke
            else "published"
            if self.published
            else "cancelled"
            if self.cancelled
            else "blocked"
            if self.blocked
            else "awaiting_publication"
            if self.state == "succeeded"
            else self.state
        )
        return {
            "state": state,
            "prediction_ready": state == "published",
            "provider_requests": 0,
            "operation_id": job["operation_id"],
        }

    def enqueue(self, body, reference, authority):
        self.record = {
            "body": deepcopy(body),
            "request_id": body["command"],
            "operation_id": str(uuid4()),
            "input_ref": reference,
            "authority_digest": authority,
        }
        return self.view(self.record)

    def publishable(self, job):
        if self.state != "succeeded" or self.cancelled or self.blocked:
            raise GovernanceError("DENIED", "not publishable")

    def output(self, job):
        self.publishable(job)
        return deepcopy(self.result)

    def commit(self, *args):
        self.publishable(self.record)
        value = super().commit(*args)
        self.commits += 1
        self.mark_published(self.record)
        return value

    def mark_published(self, job):
        self.publishable(job)
        if self.revoke or not self.receipt:
            raise GovernanceError("DENIED", "authority")
        self.published = True

    def block(self, job):
        self.blocked = True
        return self.view(job)

    def cancel(self, job):
        if self.published:
            raise GovernanceError("DENIED", "published immutable")
        self.cancelled = True
        return self.view(job)


@pytest.fixture
def case():
    packet, cert = setup()
    tx = Transactions(packet)
    store = Store()
    jobs = Jobs(tx, store)
    args = ("owner", str(uuid4()), str(uuid4()), cert, str(uuid4()))
    return tx, store, jobs, args


def finish(tx, store, executor=compute):
    assert not tx.active
    tx.result = worker.calculate(tx.record, executor, store)
    tx.state = "succeeded"


def test_submit_queue_compute_publish_read_and_lost_ack(case):
    tx, store, jobs, args = case
    first = jobs.submit(*args)
    assert first["state"] == "queued" and not first["prediction_ready"]
    assert jobs.submit(*args) == first
    read = (args[0], args[1], args[2], args[4])
    assert jobs.advance(*read)["state"] == "queued"
    finish(tx, store)
    assert jobs.read(*read)["state"] == "awaiting_publication"
    assert jobs.advance(*read)["state"] == "published"
    assert jobs.advance(*read)["state"] == "published" and tx.commits == 1
    assert "value" not in jobs.read(*read)
    tx.revoke = True
    assert jobs.read(*read)["state"] == "stale"


def test_actual_private_material_worker_and_original_prediction_publication(source):
    root, index, packet, _ = source
    tx = Transactions(deepcopy(packet))
    store = Store()
    jobs = Jobs(tx, store)
    args = (
        "owner",
        str(uuid4()),
        str(uuid4()),
        packet["authority"]["certificate"]["id"],
        str(uuid4()),
    )
    jobs.submit(*args)
    finish(tx, store, Executor(root, index))
    assert jobs.advance(args[0], args[1], args[2], args[4])["state"] == "published"
    assert 0 <= float(tx.receipt["value"]) <= 100


@pytest.mark.parametrize("when", ["queued", "computed", "during_read"])
def test_cancel_before_publication_is_terminal(case, when):
    tx, store, jobs, args = case
    jobs.submit(*args)
    read = (args[0], args[1], args[2], args[4])
    if when != "queued":
        finish(tx, store)
    if when == "during_read":
        original = store.get

        def get(key):
            tx.cancelled = True
            return original(key)

        store.get = get
        assert jobs.advance(*read)["state"] == "cancelled"
    else:
        assert jobs.cancel(*read)["state"] == "cancelled"
        assert jobs.cancel(*read)["state"] == "cancelled"
        assert jobs.advance(*read)["state"] == "cancelled"
    assert tx.receipt is None


@pytest.mark.parametrize(
    "attack", ["revoke", "input", "result", "method", "cross_member", "lease_running", "failed"]
)
def test_rejects_drift_or_partial_results(case, attack):
    tx, store, jobs, args = case
    jobs.submit(*args)
    finish(tx, store)
    read = [args[0], args[1], args[2], args[4]]
    if attack == "revoke":
        tx.revoke = True
    if attack == "input":
        tx.packet["reference"] = {"changed": True}
    if attack == "result":
        store.values[tx.result["result_ref"]]["value"] = "NaN"
    if attack == "method":
        store.values[tx.record["input_ref"]]["prediction_method"] = "f" * 64
    if attack == "cross_member":
        read[0] = "other"
    if attack == "lease_running":
        tx.state = "running"
    if attack == "failed":
        tx.state = "failed"
    if attack == "cross_member":
        with pytest.raises((GovernanceError, ValueError)):
            jobs.advance(*read)
    else:
        state = jobs.advance(*read)["state"]
        assert state == ({"lease_running": "running", "failed": "failed"}.get(attack, "blocked"))
        assert jobs.advance(*read)["state"] == state
    assert tx.receipt is None


def test_revocation_during_private_object_write_never_queues(case):
    tx, store, jobs, args = case
    store.hook = lambda: setattr(tx, "revoke", True)
    with pytest.raises(GovernanceError):
        jobs.submit(*args)
    assert tx.record is None


def test_worker_default_disabled_and_opaque_effect(case, monkeypatch):
    from packages.domain.errors import DomainError

    tx, store, jobs, args = case
    jobs.submit(*args)
    monkeypatch.setattr(worker, "_executor", None)
    with pytest.raises(DomainError):
        worker.compute({})
    outcome = worker.calculate(tx.record, compute, store)
    assert set(outcome) == {"input_ref", "result_ref"}
    monkeypatch.setattr(worker, "record", lambda *args: tx.record)
    assert worker.publish(None, {}, outcome) == outcome
    with pytest.raises(DomainError):
        worker.publish(None, {}, outcome | {"value": "50"})


def test_runtime_default_off_and_publishes_without_browser(case, monkeypatch):
    tx, store, jobs, args = case
    jobs.submit(*args)
    finish(tx, store)
    monkeypatch.setattr(runtime, "_service", None)
    assert runtime.drain() == {"processed": 0, "blocked": 0}

    class Rows:
        def fetchall(self):
            return [{"payload": tx.record}]

    class Conn:
        def execute(self, *args):
            return Rows()

    @contextmanager
    def connections():
        yield Conn()

    monkeypatch.setattr(runtime, "_service", jobs)
    monkeypatch.setattr(runtime, "_connections", connections)
    assert runtime.drain()["processed"] == 1 and tx.published


@pytest.mark.parametrize(
    "attack", ["expired", "owner", "fence", "generation", "cancelled", "duplicate"]
)
def test_existing_engine_fences_prediction_handler(case, monkeypatch, attack):
    from datetime import UTC, datetime, timedelta

    from apps.worker import engine
    from packages.package_prediction_tasks.application import STEP

    tx, store, jobs, args = case
    jobs.submit(*args)
    job = tx.record
    at = datetime.now(UTC)
    message = {
        "schema_version": 1,
        "event_type": "step.requested",
        "event_id": str(uuid4()),
        "operation_id": job["operation_id"],
        "bid_id": args[1],
        "step_key": STEP,
        "input_digest": job["input_ref"],
        "generation": 1,
        "handler_version": HANDLER,
        "payload_ref": args[4],
        "created_at": at.isoformat(),
    }
    op = {
        "id": job["operation_id"],
        "state": "cancel_requested" if attack == "cancelled" else "running",
    }
    plan = {"dispatch_generation": 2 if attack == "generation" else 1}
    receipt = {
        "state": "running",
        "fence": 2 if attack == "fence" else 1,
        "owner_token": "other" if attack == "owner" else "owner",
        "lease_until": at - timedelta(seconds=1)
        if attack == "expired"
        else at + timedelta(seconds=60),
    }
    calls = []

    class Result:
        def fetchone(self):
            return {"exists": True} if attack == "duplicate" else None

    class Conn:
        def execute(self, query, params):
            calls.append(query)
            return Result()

    @contextmanager
    def connections(*args):
        yield Conn()

    monkeypatch.setattr(engine, "connection", connections)
    monkeypatch.setattr(engine, "require_read_committed", lambda c: None)
    monkeypatch.setattr(engine, "now", lambda: at)

    def fetch(c, query, args):
        if "FROM operations " in query:
            return op
        if "FROM operation_steps " in query:
            return plan
        return receipt

    monkeypatch.setattr(engine, "fetch", fetch)
    assert engine.finish(
        message, {"owner": "owner", "fence": 1}, {"input_ref": "a" * 64, "result_ref": "b" * 64}
    ) is (attack == "duplicate")
    assert not any(query.startswith(("UPDATE", "INSERT")) for query in calls)
    assert (
        HANDLER in engine.LANE_HANDLERS["review"]
        and engine.task_topic(HANDLER) == "tender.task.review.v1"
    )


def test_native_publication_checks_terminal_lease_and_opaque_effect(monkeypatch):
    from packages.package_prediction_tasks import native

    job = {
        "body": {"bid": "bid"},
        "operation_id": "operation",
        "input_ref": "a" * 64,
        "request_id": "cmd",
    }

    class Empty:
        def fetchone(self):
            return None

    class Conn:
        def execute(self, *args):
            return Empty()

    tx = native.Transaction(Conn())
    monkeypatch.setattr(native, "assert_work_writable", lambda *args: None)
    monkeypatch.setattr(tx, "operation", lambda job: {"state": "succeeded"})
    monkeypatch.setattr(tx, "cancelled", lambda job: False)
    stage = {
        "state": "succeeded",
        "lease_until": None,
        "input_digest": "a" * 64,
        "handler_version": HANDLER,
    }
    monkeypatch.setattr(native, "fetch", lambda *args: stage)
    tx.publishable(job)
    stage["lease_until"] = "still leased"
    with pytest.raises(GovernanceError):
        tx.publishable(job)


def test_composition_never_discovers_credentials():
    from types import SimpleNamespace

    from packages.package_prediction_tasks.composition import api

    with pytest.raises(ValueError):
        api(SimpleNamespace(), object())
    from packages.package_model_live.producer import Executor
    from packages.package_prediction_tasks.worker import configure

    with pytest.raises(ValueError):
        configure(Executor("private-store", object()))


def test_revoke_between_result_load_and_final_publish_blocks_atomically(case):
    tx, store, jobs, args = case
    jobs.submit(*args)
    finish(tx, store)
    original = store.get

    def get(key):
        value = original(key)
        if key == tx.result["result_ref"]:
            tx.revoke = True
        return value

    store.get = get
    assert jobs.advance(args[0], args[1], args[2], args[4])["state"] == "blocked"
    assert tx.receipt is None


def test_private_objects_roundtrip_and_corruption_no_public_registration(monkeypatch):
    from packages.domain import storage
    from packages.package_prediction_tasks.storage import Objects

    values = {}
    monkeypatch.setattr(storage, "put", lambda key, data, media: values.update({key: data}))
    monkeypatch.setattr(storage, "get", lambda key: values[key])
    store = Objects()
    reference = store.put({"value": "50", "input": "fixed"})
    assert store.get(reference) == {"value": "50", "input": "fixed"}
    for damaged in (b'{"value":"60"}', b"{invalid", b"\xff"):
        values["blobs/" + reference] = damaged
        with pytest.raises(GovernanceError):
            store.get(reference)
    with pytest.raises(GovernanceError):
        store.get("../private")


def test_task_http_default_disabled_closed_body_and_replay(case, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from apps.api import package_prediction_task_routes as routes
    from packages.domain.errors import DomainError

    tx, store, jobs, args = case
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(routes, "auth", lambda *args: {"member_id": "owner"})

    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    base = f"/api/v1/bids/{args[1]}/technical-scopes/{args[2]}/prediction-tasks"
    body = {"certificate_id": args[3], "command_id": args[4]}
    client = TestClient(app)
    assert client.post(base, json=body).status_code == 503
    app.state.package_prediction_jobs = jobs
    first = client.post(base, json=body)
    assert first.status_code == 202 and first.json()["state"] == "queued"
    assert client.post(base, json=body).json() == first.json()
    response = client.get(base + "/" + args[4])
    assert response.headers["cache-control"] == "private, no-store"
    assert (
        client.post(base + "/" + args[4] + "/advance", json={"verified": True}).status_code == 422
    )
