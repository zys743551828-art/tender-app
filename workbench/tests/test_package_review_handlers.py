"""SQLite publication/query checks and explicit fake generation, without paid effects.

Admission/source ports are the separately tested synthetic ports. These tests do
not claim PostgreSQL role/fence coverage or real model quality.
"""
# ruff: noqa: F401,F811

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest
from test_bid_package_scope_review import observe, ports
from test_package_scope_review import case, response, uid

from apps.worker import package_review_handlers as worker
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


@pytest.fixture
def runtime(ports, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-only-never-sent")
    observed = observe(ports, worker=True)
    manifest = observed.input_manifest()
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("ATTACH DATABASE ':memory:' AS design")
    db.executescript(
        """
        CREATE TABLE design.operations(id TEXT PRIMARY KEY,bid_id TEXT,state TEXT);
        CREATE TABLE design.bid_package_review_runs(
          id TEXT PRIMARY KEY,bid_id TEXT,execution_input_id TEXT,operation_id TEXT,
          input_manifest TEXT,input_digest TEXT);
        CREATE TABLE design.model_calls(
          id TEXT PRIMARY KEY,operation_id TEXT,logical_call_key TEXT,attempt_no INTEGER,state TEXT);
        CREATE TABLE design.bid_package_review_results(
          run_id TEXT PRIMARY KEY,bid_id TEXT,operation_id TEXT,manifest TEXT,digest TEXT);
        """
    )
    message = {
        "handler_version": worker.policy.HANDLER,
        "step_key": worker.policy.STEP,
        "payload_ref": uid(50),
        "bid_id": manifest["scope"]["bid_id"],
        "operation_id": uid(51),
        "input_digest": digest(manifest),
        "generation": 1,
    }
    db.execute(
        "INSERT INTO design.operations VALUES(?,?,?)", (uid(51), message["bid_id"], "running")
    )
    db.execute(
        "INSERT INTO design.bid_package_review_runs VALUES(?,?,?,?,?,?)",
        (
            uid(50),
            message["bid_id"],
            manifest["execution_input"]["id"],
            uid(51),
            json.dumps(manifest),
            digest(manifest),
        ),
    )
    db.commit()
    state = {
        "db": db,
        "ports": ports,
        "manifest": manifest,
        "message": message,
        "calls": [],
        "lease_live": True,
        "alter_response": None,
    }

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Connection:
        autocommit = False

        def execute(self, sql, parameters=()):
            ports["events"].append(sql)
            if sql.startswith("SET TRANSACTION") or sql.startswith("SELECT design.lock_worker_bid"):
                return Cursor([])
            if sql == "SHOW transaction_isolation":
                return Cursor([{"transaction_isolation": "read committed"}])
            values = tuple(
                json.dumps(item.obj) if hasattr(item, "obj") else item for item in parameters
            )
            cursor = db.execute(sql.replace("%s", "?"), values)
            rows = []
            if cursor.description:
                for value in cursor.fetchall():
                    row = dict(value)
                    for key in ("input_manifest", "manifest"):
                        if key in row:
                            row[key] = json.loads(row[key])
                    rows.append(row)
            return Cursor(rows)

    @contextmanager
    def connection(is_worker=False):
        assert is_worker is True
        ports["active"] += 1
        try:
            yield Connection()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            ports["active"] -= 1

    def execution_lock(c, task, lease):
        assert ports["active"] > 0
        if not state["lease_live"]:
            raise DomainError("MODEL_EXECUTION_STALE", "explicit lease simulation")
        ports["events"].append("execution-lock")

    def generate(task, lease, **kwargs):
        assert ports["active"] == 0
        state["calls"].append(deepcopy(kwargs))
        batch = json.loads(kwargs["messages"][1]["content"])
        value = response(batch)
        if state["alter_response"]:
            state["alter_response"](value)
        call_id = uid(900 + len(state["calls"]))
        db.execute(
            "INSERT INTO design.model_calls VALUES(?,?,?,?,?)",
            (call_id, task["operation_id"], kwargs["logical_key"], 1, "succeeded"),
        )
        db.commit()
        return {"data": value, "model": "deepseek-flash"}, call_id

    monkeypatch.setattr(worker, "connection", connection)
    monkeypatch.setattr(worker.model_calls, "lock_execution", execution_lock)
    monkeypatch.setattr(worker.model_calls, "generate", generate)
    state["Connection"] = Connection
    state["connection"] = connection
    yield state
    db.close()


def compute(runtime):
    return worker.compute(runtime["message"], {"owner": uid(90), "fence": 1})


def publish(runtime, outcome):
    with runtime["connection"](True) as c:
        return worker.publish(c, runtime["message"], outcome)


def result_count(runtime):
    return (
        runtime["db"]
        .execute("SELECT count(*) FROM design.bid_package_review_results")
        .fetchone()[0]
    )


def test_full_scope_worker_publishes_exact_result_only_after_closed_io(runtime):
    outcome = compute(runtime)
    assert result_count(runtime) == 0
    assert "private" not in repr(outcome)
    assert len(runtime["calls"]) == 1
    call = runtime["calls"][0]
    assert call["logical_key"] == "package-scope-judgment-1"
    assert call["max_tokens"] == 8192 and call["purpose"] == "core_review"
    payload = json.loads(call["messages"][1]["content"])
    assert [doc["member_id"] for doc in payload["documents"]] == [
        "main-bid",
        "business-bid",
        "authority",
    ]
    assert "unused-private" not in json.dumps(payload)
    runtime["ports"]["events"].clear()
    effect = publish(runtime, outcome)
    saved = runtime["db"].execute("SELECT * FROM design.bid_package_review_results").fetchone()
    result = json.loads(saved["manifest"])
    assert digest(result) == saved["digest"] == effect["result_digest"]
    assert result["input_digest"] == runtime["message"]["input_digest"]
    assert result["overall_coverage"] == "partial" and result["matrix_coverage"] == "complete"
    assert (
        result["execution_digest"]
        == runtime["manifest"]["execution_input"]["identity"]["execution_digest"]
    )
    assert "original-io" not in runtime["ports"]["events"]
    assert not result["formal_scoring_eligible"] and not result["submission_eligible"]


def test_worker_submits_and_hashes_the_same_complete_float_geometry(runtime):
    ports = runtime["ports"]
    root = ports["frozen"].evidence()
    block = root["documents"][0]["blocks"][0]
    block["bbox"] = [0.0, -0.0, 17.125, 841.8897637795277]
    block["structure"] = {"table": {"cells": [{"row": 0, "width": 12.000000000000002}]}}
    ports["frozen"] = replace(ports["frozen"], _evidence_text=json.dumps(root))
    ports["snapshot"]["documents"][0]["blocks"] = [deepcopy(block)]
    ports["prepared"] = replace(
        ports["prepared"],
        _snapshot_text=json.dumps(
            ports["snapshot"] | {"version": "package-review-prepared-snapshot/1"}
        ),
    )
    manifest = observe(ports, worker=True).input_manifest()
    runtime["manifest"] = manifest
    runtime["message"]["input_digest"] = digest(manifest)
    runtime["db"].execute(
        "UPDATE design.bid_package_review_runs SET input_manifest=?,input_digest=? WHERE id=?",
        (json.dumps(manifest), digest(manifest), runtime["message"]["payload_ref"]),
    )
    runtime["db"].commit()
    outcome = compute(runtime)
    text = runtime["calls"][0]["messages"][1]["content"]
    actual = json.loads(text)
    assert text == worker.policy.model_json(actual)
    assert actual["documents"][0]["blocks"][0] == block
    assert actual.pop("scope_digest") == worker.policy.model_digest(actual["documents"])
    assert worker.policy.model_digest(actual) == manifest["model_input_digest"]
    effect = publish(runtime, outcome)
    assert effect["overall_coverage"] == "partial" and result_count(runtime) == 1


@pytest.mark.parametrize(
    "field",
    ["bid_id", "payload_ref", "operation_id", "input_digest", "handler_version", "step_key"],
)
def test_task_scope_and_input_binding_fail_before_any_provider_call(runtime, field):
    runtime["message"][field] = "0" * 64 if field == "input_digest" else uid(999)
    with pytest.raises(DomainError):
        compute(runtime)
    assert not runtime["calls"] and result_count(runtime) == 0


def test_lease_loss_before_remote_request_does_not_invoke_provider(runtime):
    runtime["lease_live"] = False
    with pytest.raises(DomainError) as error:
        compute(runtime)
    assert error.value.code == "MODEL_EXECUTION_STALE"
    assert not runtime["calls"] and result_count(runtime) == 0


@pytest.mark.parametrize("change", ["source", "fact_scope", "plan", "method"])
def test_late_current_authority_changes_prevent_result_insert(runtime, monkeypatch, change):
    outcome = compute(runtime)
    state = runtime["ports"]
    if change == "source":
        state["snapshot"]["observations"]["sources"] = "withdrawn"
    elif change == "fact_scope":
        state["admission"]["content_digest"] = "0" * 64
        state["proof_text"] = "scope-revoked"
    elif change == "plan":
        state["plan"]["digest"] = "0" * 64
    else:
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    with pytest.raises(DomainError):
        publish(runtime, outcome)
    assert result_count(runtime) == 0


@pytest.mark.parametrize("change", ["state", "operation", "logical_key", "attempt"])
def test_model_receipt_must_be_successful_for_exact_operation_batch_and_attempt(runtime, change):
    outcome = compute(runtime)
    assignments = {
        "state": ("state", "unknown"),
        "operation": ("operation_id", uid(999)),
        "logical_key": ("logical_call_key", "old-core-judgment"),
        "attempt": ("attempt_no", 2),
    }
    column, value = assignments[change]
    runtime["db"].execute("UPDATE design.model_calls SET " + column + "=?", (value,))
    runtime["db"].commit()
    with pytest.raises(DomainError) as error:
        publish(runtime, outcome)
    assert error.value.code == "PACKAGE_SCOPE_MODEL_RECEIPT_MISSING"
    assert result_count(runtime) == 0


def test_model_partial_range_cannot_publish_even_after_successful_call_receipt(runtime):
    runtime["alter_response"] = lambda value: value.update(judgments=[])
    with pytest.raises(DomainError) as error:
        compute(runtime)
    assert error.value.code == "PACKAGE_SCOPE_RANGE_INCOMPLETE"
    assert len(runtime["calls"]) == 1 and result_count(runtime) == 0


def test_publication_revalidates_returned_matrix_and_requires_every_batch(runtime):
    outcome = compute(runtime)
    saved = deepcopy(outcome._responses)
    outcome._responses[0]["data"]["judgments"][0]["target_quotes"][0]["quote"] = "伪造的 95 天"
    with pytest.raises(DomainError):
        publish(runtime, outcome)
    outcome._responses[:] = saved
    outcome._responses.clear()
    with pytest.raises(DomainError) as error:
        publish(runtime, outcome)
    assert error.value.code == "PACKAGE_SCOPE_RANGE_INCOMPLETE" and result_count(runtime) == 0


def test_replaced_immutable_run_binding_is_rejected_before_publication(runtime):
    outcome = compute(runtime)
    manifest = deepcopy(runtime["manifest"])
    manifest["dependency_plan"]["id"] = uid(999)
    runtime["db"].execute(
        "UPDATE design.bid_package_review_runs SET input_manifest=?,input_digest=?",
        (json.dumps(manifest), digest(manifest)),
    )
    runtime["db"].commit()
    with pytest.raises(DomainError) as error:
        publish(runtime, outcome)
    assert error.value.code == "PACKAGE_SCOPE_TASK_BINDING_INVALID"
    assert result_count(runtime) == 0
