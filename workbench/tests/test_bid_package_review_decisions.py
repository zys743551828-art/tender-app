"""Actual service/Command SQL on SQLite; PG trigger/role coverage lives in the API suite.

Only PostgreSQL locking/casts/clock and the already-tested immutable run reader are
explicit adapters. No model/provider/original access is used by human decisions.
"""
# ruff: noqa: F401,F811

import json
import re
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from test_package_review_decisions import case, report, request, uid

from packages.contracts.package_review_decisions_api import valid
from packages.domain import bid_package_review_decisions as service
from packages.domain.runtime import DomainError
from packages.identity import pagination


@pytest.fixture
def ledger(report, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "explicit-synthetic-cursor-key")
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("ATTACH DATABASE ':memory:' AS design")
    db.executescript(
        """
        CREATE TABLE design.commands(id TEXT PRIMARY KEY,actor_id TEXT,command_kind TEXT,target_id TEXT,
         idempotency_key TEXT,request_digest TEXT,response TEXT,
         UNIQUE(actor_id,command_kind,target_id,idempotency_key));
        CREATE TABLE design.bids(id TEXT PRIMARY KEY,revision INTEGER);
        CREATE TABLE design.bid_profiles(bid_id TEXT PRIMARY KEY,phase TEXT,archived_at TEXT);
        CREATE TABLE design.bid_package_review_decisions(
         id TEXT PRIMARY KEY,bid_id TEXT,run_id TEXT,requirement_id TEXT,actor_id TEXT,command_id TEXT UNIQUE,
         sequence_no INTEGER,previous_id TEXT,previous_digest TEXT,manifest TEXT,digest TEXT,created_at TEXT,
         UNIQUE(bid_id,run_id,requirement_id,sequence_no));
        CREATE TABLE design.bid_package_review_decision_heads(
         bid_id TEXT,run_id TEXT,requirement_id TEXT,decision_id TEXT,digest TEXT,sequence_no INTEGER,
         PRIMARY KEY(bid_id,run_id,requirement_id));
        CREATE TABLE design.audit_entries(id TEXT,actor_id TEXT,bid_id TEXT,command_id TEXT,event_type TEXT,payload TEXT);
        CREATE TABLE design.stream_heads(id TEXT,bid_id TEXT,last_seq INTEGER);
        CREATE TABLE design.stream_events(stream_id TEXT,seq INTEGER,event_id TEXT,event_type TEXT,payload TEXT);
        """
    )
    db.execute("INSERT INTO design.bids VALUES(?,1)", (report["scope"]["bid_id"],))
    db.execute(
        "INSERT INTO design.bid_profiles VALUES(?,'working',NULL)", (report["scope"]["bid_id"],)
    )
    db.commit()
    state = {
        "db": db,
        "report": report,
        "events": [],
        "fail_on": None,
        "isolation": "read committed",
        "clock": 0,
    }

    class Cursor:
        def __init__(self, rows, rowcount=0):
            self.rows, self.rowcount = rows, rowcount

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Connection:
        autocommit = False

        def __init__(self):
            self.isolation = state["isolation"]

        def execute(self, sql, parameters=()):
            state["events"].append(sql)
            if state["fail_on"] and sql.startswith(state["fail_on"]):
                raise RuntimeError("explicit transaction failure")
            if sql.startswith("SET TRANSACTION"):
                self.isolation = "repeatable read"
                return Cursor([])
            if sql == "SHOW transaction_isolation":
                return Cursor([{"transaction_isolation": self.isolation}])
            if sql == "SELECT clock_timestamp() AS at":
                state["clock"] += 1
                return Cursor(
                    [
                        {
                            "at": datetime(2026, 10, 21, tzinfo=timezone.utc)
                            + timedelta(microseconds=state["clock"])
                        }
                    ]
                )
            sql = sql.replace("%s::bigint", "CAST(%s AS INTEGER)").replace("%s::uuid", "%s")
            sql = re.sub(r" FOR UPDATE(?: OF h)?", "", sql).replace("%s", "?")
            values = tuple(
                json.dumps(value.obj, ensure_ascii=False)
                if hasattr(value, "obj")
                else str(value)
                if isinstance(value, UUID)
                else value
                for value in parameters
            )
            cursor = db.execute(sql, values)
            rows = []
            if cursor.description:
                for item in cursor.fetchall():
                    row = dict(item)
                    for key in ("manifest", "response", "payload"):
                        if row.get(key) is not None:
                            row[key] = json.loads(row[key])
                    rows.append(row)
            return Cursor(rows, cursor.rowcount)

    @contextmanager
    def connection(worker=False):
        assert worker is False
        try:
            yield Connection()
            db.commit()
        except Exception:
            db.rollback()
            raise

    def load(c, scope, frozen_id, prepared_id, run_id):
        state["events"].append("immutable-run-read")
        value = state["report"]
        if (
            tuple(value["scope"][key] for key in service.policy.SCOPE_KEYS) != scope
            or value["frozen_input_id"] != frozen_id
            or value["execution_input_id"] != prepared_id
            or value["id"] != run_id
        ):
            raise DomainError("PACKAGE_REVIEW_RUN_NOT_FOUND", "explicit foreign scope", 404)
        return deepcopy(value)

    monkeypatch.setattr(service, "connection", connection)
    monkeypatch.setattr(service.runs, "load", load)
    state["args"] = (
        tuple(report["scope"][key] for key in service.policy.SCOPE_KEYS),
        report["frozen_input_id"],
        report["execution_input_id"],
        report["id"],
    )
    state["requirement_id"] = report["result"]["manifest"]["matrix"][0]["requirement_id"]
    yield state
    db.close()


def save(ledger, body=None, *, key=None):
    return service.save(
        uid(60),
        *ledger["args"],
        ledger["requirement_id"],
        key or uid(80),
        request(ledger["report"]) if body is None else body,
    )


def totals(ledger):
    return tuple(
        ledger["db"].execute("SELECT count(*) FROM design." + table).fetchone()[0]
        for table in (
            "commands",
            "bid_package_review_decisions",
            "bid_package_review_decision_heads",
            "audit_entries",
        )
    )


def test_exact_ack_replay_precedes_changed_head_closed_work_and_any_current_read(ledger):
    body = request(ledger["report"])
    first, replayed = save(ledger, body)
    assert not replayed and first["status"] == 201
    head = {"id": first["body"]["manifest"]["id"], "digest": first["body"]["digest"]}
    second, _ = save(
        ledger, request(ledger["report"], expected=head, state="rejected"), key=uid(81)
    )
    ledger["db"].execute("UPDATE design.bid_profiles SET phase='closed'")
    ledger["db"].commit()
    ledger["events"].clear()
    again, replayed = save(ledger, body)
    assert replayed and again == first and totals(ledger) == (2, 2, 1, 2)
    assert "immutable-run-read" not in ledger["events"]
    assert not any("INSERT" in sql or "UPDATE" in sql for sql in ledger["events"])
    current = service.current(*ledger["args"])
    summary = current["items"][0]["current"]
    assert valid("PackageReviewHumanDecisionCurrent", current)
    assert summary["id"] == second["body"]["manifest"]["id"] and summary["state"] == "rejected"
    assert "selected_quotes" not in json.dumps(current) and "quote" not in summary
    with pytest.raises(DomainError) as error:
        save(ledger, key=uid(82))
    assert error.value.code == "PROJECT_WORK_CLOSED" and totals(ledger) == (2, 2, 1, 2)


def test_stale_cas_different_body_and_cross_scope_cannot_add_commands_or_opinions(ledger):
    first, _ = save(ledger)
    expected = {"id": first["body"]["manifest"]["id"], "digest": first["body"]["digest"]}
    with pytest.raises(DomainError) as error:
        save(ledger, key=uid(81))
    assert error.value.code == "PACKAGE_REVIEW_DECISION_HEAD_CHANGED"
    with pytest.raises(DomainError) as error:
        save(ledger, request(ledger["report"], expected=expected, state="needs_review"))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    args = list(ledger["args"])
    args[1] = uid(999)
    with pytest.raises(DomainError) as error:
        service.save(uid(60), *args, ledger["requirement_id"], uid(80), request(ledger["report"]))
    assert error.value.code == "PACKAGE_REVIEW_DECISION_NOT_FOUND"
    assert totals(ledger) == (1, 1, 1, 1)


@pytest.mark.parametrize(
    "failure",
    [
        "INSERT INTO design.bid_package_review_decision_heads",
        "INSERT INTO audit_entries",
        "UPDATE commands SET response",
    ],
)
def test_head_audit_or_ack_failure_rolls_back_entire_opinion(ledger, failure):
    ledger["fail_on"] = failure
    with pytest.raises(RuntimeError, match="explicit transaction failure"):
        save(ledger)
    assert totals(ledger) == (0, 0, 0, 0)
    ledger["fail_on"] = None
    result, _ = save(ledger)
    assert result["body"]["manifest"]["sequence_no"] == 1 and totals(ledger) == (1, 1, 1, 1)


def test_cas_update_failure_keeps_previous_head_and_exact_history(ledger):
    first, _ = save(ledger)
    old = first["body"]
    body = request(
        ledger["report"], expected={"id": old["manifest"]["id"], "digest": old["digest"]}
    )
    ledger["fail_on"] = "UPDATE design.bid_package_review_decision_heads"
    with pytest.raises(RuntimeError):
        save(ledger, body, key=uid(81))
    assert totals(ledger) == (1, 1, 1, 1)
    ledger["fail_on"] = None
    assert service.current(*ledger["args"])["items"][0]["current"]["digest"] == old["digest"]


def test_current_is_one_summary_and_history_is_bounded_signed_keyset(ledger, monkeypatch):
    head = None
    values = []
    for index in range(22):
        body = request(ledger["report"], expected=head, state="needs_review") | {
            "selected_quotes": []
        }
        saved, _ = save(ledger, body, key=uid(100 + index))
        values.append(saved["body"])
        head = {"id": saved["body"]["manifest"]["id"], "digest": saved["body"]["digest"]}
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://unavailable.example/token=never-read")
    current = service.current(*ledger["args"])
    assert len(current["items"]) == 1 and current["items"][0]["current"]["sequence_no"] == 22
    page = service.history(*ledger["args"], ledger["requirement_id"])
    assert valid("PackageReviewHumanDecisionPage", page)
    assert (
        page["has_more"]
        and len(page["items"]) == 20
        and page["items"] == list(reversed(values[2:]))
    )
    next_page = service.history(
        *ledger["args"], ledger["requirement_id"], cursor=page["next_cursor"]
    )
    assert next_page["items"] == list(reversed(values[:2])) and not next_page["has_more"]
    assert next_page["next_cursor"] is None
    with pytest.raises(DomainError) as error:
        service.history(
            *ledger["args"],
            ledger["requirement_id"],
            cursor=pagination.encode("foreign", ["22", uid(70)]),
        )
    assert error.value.code == "INVALID_CURSOR"
    with pytest.raises(DomainError):
        service.history(*ledger["args"], ledger["requirement_id"], limit=21)


def test_new_opinions_require_read_committed_and_generic_audit_has_no_quote_or_reason(ledger):
    ledger["isolation"] = "repeatable read"
    with pytest.raises(DomainError) as error:
        save(ledger)
    assert error.value.code == "CURRENT_AUTHORITY_REQUIRES_READ_COMMITTED"
    assert totals(ledger) == (0, 0, 0, 0)
    ledger["isolation"] = "read committed"
    save(ledger)
    audit = json.loads(
        ledger["db"].execute("SELECT payload FROM design.audit_entries").fetchone()[0]
    )
    assert set(audit) == {
        "decision_id",
        "decision_digest",
        "run_id",
        "requirement_id",
        "result_digest",
        "row_digest",
        "state",
        "previous_decision_id",
    }


def test_corrupt_head_cannot_silently_fall_back_to_unreviewed(ledger):
    save(ledger)
    ledger["db"].execute(
        "UPDATE design.bid_package_review_decision_heads SET digest=?", ("0" * 64,)
    )
    ledger["db"].commit()
    with pytest.raises(DomainError) as error:
        service.current(*ledger["args"])
    assert error.value.code == "PACKAGE_REVIEW_DECISION_CORRUPT"
