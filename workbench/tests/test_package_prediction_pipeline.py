"""Project intent through real task/worker consumers; authority is explicitly simulated."""

# ruff: noqa: F811
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_package_prediction import setup
from test_package_prediction_reports import cohort, material, mirror, source  # noqa: F401
from test_package_prediction_tasks import Store, finish
from test_package_prediction_tasks import Transactions as TaskTx

from packages.domain.errors import DomainError
from packages.package_prediction_pipeline.application import Pipeline
from packages.package_prediction_tasks.application import Jobs


class Repository:
    def __init__(self, tx, args):
        self.tx, self.args = tx, args
        self.saved = None
        self.cancelled_flag = self.rejected_flag = False
        self.context_value = {
            "state": "ready",
            "snapshot": {
                "review_id": str(uuid4()),
                "scope_digest": "a" * 64,
                "trigger": "start_review",
            },
        }
        self.eligible = [args[3]]
        self.saves = 0
        self.ready = True

    @contextmanager
    def __call__(self, actor, bid, scope):
        if (actor, bid, scope) != self.args[:3]:
            raise DomainError("DENIED", "actor mismatch", 403)
        yield self

    def context(self):
        return deepcopy(self.context_value)

    def plan(self):
        return deepcopy(self.saved)

    def candidates(self):
        return self.eligible.copy()

    def save(self, plan):
        assert self.saved is None
        self.saved = deepcopy(plan)
        self.saves += 1

    def cancelled(self, plan):
        return self.cancelled_flag

    def rejected(self, plan):
        return self.rejected_flag

    def reject(self, plan):
        self.rejected_flag = True

    def cancel(self, plan):
        if self.tx.record:
            self.tx.cancel(self.tx.record)
        self.cancelled_flag = True

    def job(self, plan):
        return self.tx.view(self.tx.record) if self.tx.record else None

    def report_ready(self, plan):
        return self.ready and not self.tx.revoke

    def guard(self):
        if self.saved and (
            self.cancelled_flag
            or self.rejected_flag
            or self.context_value.get("snapshot") != self.saved["snapshot"]
        ):
            raise DomainError("PREDICTION_INTENT_CHANGED", "changed", 409)


@pytest.fixture
def pipeline(monkeypatch):
    packet, cert = setup()
    tx, store = TaskTx(packet), Store()
    args = ("owner", str(uuid4()), str(uuid4()), cert)
    repository = Repository(tx, args)
    for name in ("prepare", "enqueue", "commit"):
        original = getattr(tx, name)

        def guarded(*args, original=original):
            repository.guard()
            return original(*args)

        monkeypatch.setattr(tx, name, guarded)
    jobs = Jobs(tx, store)
    return Pipeline(repository, jobs), repository, tx, store, args[:3]


def test_existing_intent_to_queue_worker_publication_report_readiness_and_ack(pipeline):
    service, repo, tx, store, args = pipeline
    assert service.read(*args)["state"] == "awaiting_submission"
    first = service.advance(*args)
    assert first["state"] == "queued" and not first["report_ready"]
    assert service.advance(*args) == first and repo.saves == 1
    finish(tx, store)
    result = service.advance(*args)
    assert result["state"] == "ready" and result["report_ready"]
    assert result["review_id"] == repo.saved["snapshot"]["review_id"]
    assert "value" not in result and tx.commits == 1
    assert service.advance(*args) == result and tx.commits == 1
    tx.revoke = True
    assert service.read(*args)["state"] == "stale"


@pytest.mark.parametrize("state", ["waiting_start", "waiting_review", "review_failed"])
def test_unready_intent_never_submits(pipeline, state):
    service, repo, tx, _, args = pipeline
    repo.context_value = {"state": state}
    assert service.advance(*args)["state"] == state
    assert repo.saves == 0 and tx.record is None and tx.receipt is None


@pytest.mark.parametrize("count", [0, 2])
def test_no_implicit_choice_or_threshold(pipeline, count):
    service, repo, tx, _, args = pipeline
    repo.eligible = [str(uuid4()) for _ in range(count)]
    expected = "certificate_missing" if count == 0 else "certificate_ambiguous"
    assert service.read(*args)["state"] == expected
    assert service.advance(*args)["state"] == expected
    assert repo.saves == 0 and tx.record is None


@pytest.mark.parametrize("timing", ["before_submit", "during_object_write", "after_compute"])
def test_cancel_is_terminal_and_never_publishes(pipeline, timing):
    service, repo, tx, store, args = pipeline
    if timing == "before_submit":
        save = repo.save

        def cancel_after_save(plan):
            save(plan)
            repo.cancel(plan)

        repo.save = cancel_after_save
    elif timing == "during_object_write":
        store.hook = lambda: repo.cancel(repo.saved)
    state = service.advance(*args)
    if timing == "after_compute":
        finish(tx, store)
        state = service.cancel(*args, state["command_id"])
    assert state["state"] == "cancelled"
    assert service.advance(*args)["state"] == "cancelled"
    assert tx.receipt is None and tx.commits == 0


@pytest.mark.parametrize("attack", ["changed_context", "revoked", "new_method"])
def test_publish_rechecks_context_and_authority(pipeline, attack):
    service, repo, tx, store, args = pipeline
    service.advance(*args)
    finish(tx, store)
    if attack == "revoked":
        tx.revoke = True
    else:
        repo.context_value["snapshot"][attack] = "changed"
    assert service.advance(*args)["state"] in {"blocked", "context_changed"}
    assert tx.receipt is None and tx.commits == 0


def test_late_change_inside_original_job_publication_guard(pipeline):
    service, repo, tx, store, args = pipeline
    service.advance(*args)
    finish(tx, store)
    original = store.get

    def get(key):
        value = original(key)
        if key == tx.result["result_ref"]:
            repo.context_value["snapshot"]["review_id"] = str(uuid4())
        return value

    store.get = get
    service.advance(*args)
    assert tx.receipt is None and tx.blocked


def test_cross_actor_and_wrong_cancel_ack_rejected(pipeline):
    service, _, tx, _, args = pipeline
    service.advance(*args)
    with pytest.raises(DomainError):
        service.read("other", *args[1:])
    with pytest.raises(DomainError):
        service.cancel(*args, str(uuid4()))
    assert not tx.cancelled


def test_optional_sql_guards_publication_even_for_old_coordinator():
    sql = (Path(__file__).parents[1] / "deploy/sql/package-prediction-selection.sql").read_text()
    assert "BEFORE INSERT ON package_prediction.results" in sql
    assert "package_prediction.prepare(actor,bid,scope,item.id,method,cert_method)" in sql
    assert "package.prediction.pipeline_cancelled" in sql
    assert "review_result_digest" in sql and "review_input_digest" in sql
    assert "TO tender_api" in sql and "TO tender_worker" not in sql


def test_native_guard_precedes_original_prepare_enqueue_and_commit(monkeypatch):
    from packages.package_prediction_pipeline.native import GuardedTransaction, Transaction
    from packages.package_prediction_tasks.native import Transaction as Base

    tx = GuardedTransaction(object())
    tx.command = "fixed"

    class Intent:
        def guard(self, command, certificate=None):
            assert command == "fixed"
            raise DomainError("PREDICTION_INTENT_CHANGED", "cancelled", 409)

    tx.intent = Intent()
    calls = []
    for name in ("prepare", "enqueue", "commit"):
        monkeypatch.setattr(Base, name, lambda *args: calls.append(args))
        with pytest.raises(DomainError):
            getattr(tx, name)(
                *("owner", "bid", "scope", "certificate") if name == "prepare" else ()
            )
    assert not calls
    repo = Transaction(object(), "owner", "bid", "scope")
    plan = {"command": "fixed", "certificate": "certificate", "snapshot": {"review_id": "a"}}
    monkeypatch.setattr(repo, "plan", lambda: plan)
    monkeypatch.setattr(repo, "cancelled", lambda plan: False)
    monkeypatch.setattr(repo, "rejected", lambda plan: False)
    monkeypatch.setattr(repo, "context", lambda: {"snapshot": {"review_id": "b"}})
    with pytest.raises(DomainError):
        repo.guard("fixed")
    repo.guard("unrelated-manual-command")
    monkeypatch.setattr(repo, "context", lambda: {"snapshot": plan["snapshot"]})
    repo.guard("fixed", "certificate")
    with pytest.raises(DomainError):
        repo.guard("fixed", "different-certificate")


def test_runtime_default_disabled_pagination_and_resume(monkeypatch):
    from packages.package_prediction_pipeline import runtime

    monkeypatch.setattr(runtime, "_service", None)
    assert runtime.drain() == {"processed": 0, "blocked": 0}
    rows = [{"id": str(uuid4()), "actor_id": "actor", "bid_id": "bid"}]
    calls = []

    class Result:
        def fetchall(self):
            return rows.copy()

    class Connection:
        def execute(self, sql, params):
            calls.append(params)
            return Result()

    class Service:
        def advance(self, *args):
            assert args == ("actor", "bid", rows[0]["id"])

    @contextmanager
    def connections():
        yield Connection()

    monkeypatch.setattr(runtime, "_service", Service())
    monkeypatch.setattr(runtime, "_connections", connections)
    monkeypatch.setattr(runtime, "_cursor", None)
    assert runtime.drain(1)["processed"] == 1
    cursor = runtime._cursor
    rows.clear()
    assert runtime.drain(1)["processed"] == 0
    assert calls[1][:2] == (cursor, cursor) and runtime._cursor is None


def test_pipeline_http_closed_input_and_authenticated_recovery(pipeline, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from apps.api import package_prediction_pipeline_routes as routes

    service, repo, tx, store, args = pipeline
    app = FastAPI()
    app.include_router(routes.router)
    app.state.package_prediction_pipeline = service
    monkeypatch.setattr(routes, "auth", lambda *args: {"member_id": "owner"})

    @app.exception_handler(DomainError)
    async def handler(request, error):
        return JSONResponse({"code": error.code}, status_code=error.status)

    client = TestClient(app)
    base = f"/api/v1/bids/{args[1]}/technical-scopes/{args[2]}/prediction-pipeline"
    # Normalize UUID route arguments as the native adapter does.
    original = service.transactions
    service.transactions = lambda a, b, s: original(str(a), str(b), str(s))
    assert client.post(base + "/advance", json={"certificate_id": str(uuid4())}).status_code == 422
    first = client.post(base + "/advance", json={})
    assert first.status_code == 200 and first.json()["state"] == "queued"
    assert client.get(base).headers["cache-control"] == "private, no-store"
    finish(tx, store)
    assert client.post(base + "/advance", json={}).json()["report_ready"]
    monkeypatch.setattr(routes, "auth", lambda *args: {"member_id": "other"})
    assert client.get(base).status_code == 403


def test_native_context_binds_existing_start_and_ignores_score_visibility(monkeypatch):
    from packages.package_prediction_pipeline import native

    scope = {
        "actor_id": "owner",
        "digest": "a" * 64,
        "command_id": "scope-command",
        "manifest": {"preview": {"manifest": {"scope": {"bid_id": "bid"}}}},
    }
    doc = {"document_version_id": "document", "parse_run_id": "parse", "file_digest": "a" * 64}
    scope["manifest"]["preview"]["manifest"]["documents"] = [doc]
    settings = {"auto_review": False, "show_prediction": False}
    row = {
        "id": "review",
        "command_id": "review-command",
        "input_digest": "b" * 64,
        "result_digest": "c" * 64,
        "operation_state": "succeeded",
        "result_manifest": {"overall_coverage": "partial", "submitted_documents": [doc]},
    }

    from packages.domain.review_identity import digest

    row["result_digest"] = digest(row["result_manifest"])

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Connection:
        def execute(self, sql, args):
            if "members" in sql:
                return Result({"id": "owner"})
            assert "r.actor_id=%s" in sql and "input_manifest->'scope'" in sql
            return Result(row)

    monkeypatch.setattr(
        native,
        "fetch",
        lambda c, q, args: scope if "technical_scopes" in q else {"settings": settings},
    )
    monkeypatch.setattr(native, "assert_work_writable", lambda *a: None)
    monkeypatch.setattr(native.runs, "view", lambda r: r)
    checked = []
    monkeypatch.setattr(native.reports, "binding", lambda r: checked.append(r))
    tx = native.Transaction(Connection(), "owner", "bid", "scope")
    first = tx.context()
    assert first["state"] == "ready" and first["snapshot"]["trigger_id"] == "review-command"
    settings["show_prediction"] = True
    assert tx.context() == first
    settings["auto_review"] = True
    assert tx.context()["snapshot"]["trigger_id"] == "scope-command"
    row["operation_state"] = "running"
    assert tx.context()["state"] == "waiting_review"
    row["operation_state"] = "cancelled"
    assert tx.context()["state"] == "review_failed"
    assert len(checked) == 3
    row["operation_state"] = "succeeded"
    row["result_manifest"]["submitted_documents"] = [doc | {"parse_run_id": "other"}]
    row["result_digest"] = digest(row["result_manifest"])
    assert tx.context()["state"] == "review_context_mismatch"
    with pytest.raises(DomainError):
        native.Transaction(Connection(), "other", "bid", "scope").context()


def test_project_pipeline_consumes_actual_private_material_then_report(source):
    from test_package_prediction_reports import Transactions as ReportTx

    from packages.package_model_live.producer import Executor
    from packages.package_prediction_reports.application import Reports
    from packages.package_prediction_reports.projection import MaterialProjection

    root, index, packet, expected = deepcopy(source)
    tx, store = TaskTx(packet), Store()
    args = ("owner", expected["bid_id"], expected["scope_id"], expected["certificate_id"])
    repo = Repository(tx, args)
    pipeline = Pipeline(repo, Jobs(tx, store))
    pending = pipeline.advance(*args[:3])
    finish(tx, store, Executor(root, index))
    result = pipeline.advance(*args[:3])
    assert result["report_ready"] and tx.commits == 1
    assert tx.receipt["value"] == expected["value"]
    receipt = expected | {"command_id": pending["command_id"]}
    report = Reports(ReportTx(packet, receipt), MaterialProjection(root, index))
    rendered = report.render(*args[:3], pending["command_id"])
    assert rendered["command_id"] == pending["command_id"] and rendered["topics"]
    receipt.update(state="hidden", value=None, low=None, high=None)
    hidden = Reports(ReportTx(packet, receipt), MaterialProjection(root, index)).render(
        *args[:3], pending["command_id"]
    )
    assert hidden["score"] is None and hidden["topics"]


@pytest.mark.parametrize("attack", ["missing", "extra", "duplicate", "parse", "bytes", "malformed"])
def test_exact_document_set_cannot_be_inferred_from_package_scope(attack):
    from packages.package_prediction_pipeline.policy import same_documents

    doc = {"document_version_id": "document", "parse_run_id": "parse", "file_digest": "a" * 64}
    expected, actual = [doc], [doc.copy()]
    assert same_documents(expected, actual)
    if attack == "missing":
        actual = []
    if attack in {"extra", "duplicate"}:
        actual.append(doc if attack == "duplicate" else doc | {"document_version_id": "other"})
    if attack == "parse":
        actual[0]["parse_run_id"] = "other"
    if attack == "bytes":
        actual[0]["file_digest"] = "b" * 64
    if attack == "malformed":
        actual = None
    assert not same_documents(expected, actual)
