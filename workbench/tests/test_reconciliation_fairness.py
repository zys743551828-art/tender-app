"""Actual coordinator loops over synthetic SQL rows; locks/notifications are observation ports.

SQLite runs selection, joins and worker cancellation updates. This is not a PG,
Kafka, lock-race, or production capacity acceptance test.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from apps.api import review_coordinator
from apps.worker import engine

AT = datetime(2026, 10, 21, tzinfo=timezone.utc)


def identity(value):
    return str(UUID(int=value))


class LoopStop:
    def __init__(self, limit, between):
        self.cycles = 0
        self.limit = limit
        self.between = between

    def is_set(self):
        return self.cycles >= self.limit

    def wait(self, _):
        self.cycles += 1
        self.between(self.cycles)


class SweepWorld:
    def __init__(self, kind, monkeypatch):
        self.kind = kind
        self.module = engine if kind == "worker" else review_coordinator
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("now", 0, lambda: AT.isoformat())
        self.db.executescript(
            """
            CREATE TABLE operations(id TEXT PRIMARY KEY,bid_id TEXT,state TEXT,kind TEXT,
                handler_version TEXT,created_at TEXT,finished_at TEXT);
            CREATE TABLE operation_steps(operation_id TEXT,step_key TEXT,input_digest TEXT,
                dispatch_generation INTEGER,handler_version TEXT,required INTEGER,depends_on TEXT);
            CREATE TABLE step_receipts(operation_id TEXT,step_key TEXT,input_digest TEXT,
                lease_until TEXT,state TEXT,attempt_count INTEGER,fence INTEGER);
            CREATE TABLE model_calls(operation_id TEXT,state TEXT,usage TEXT);
            CREATE TABLE review_slots(bid_id TEXT PRIMARY KEY,pending_intent TEXT);
            """
        )
        self.visited = []
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(self.module, "connection", self.connection)
        monkeypatch.setattr(self.module, "assert_role", lambda *_: None)
        if kind == "worker":
            monkeypatch.setattr(engine, "now", lambda: AT)
            monkeypatch.setattr(engine, "audit", lambda *_: None)
        else:
            monkeypatch.setattr(review_coordinator, "tick", self.observe)

    def observe(self, bid):
        self.visited.append((self.stop.cycles, str(bid)))

    def add(self, number, *, created=None, active=True, cancel=False, handler="document/1"):
        key = identity(number)
        created_at = (AT + timedelta(seconds=number if created is None else created)).isoformat()
        if self.kind == "worker":
            state = "cancel_requested" if cancel else "running" if active else "succeeded"
            self.db.execute(
                "INSERT INTO operations VALUES(?,?,?,'synthetic-probe',?,?,NULL)",
                (key, key, state, handler, created_at),
            )
            self.db.execute(
                "INSERT INTO operation_steps VALUES(?,'parse',?,1,?,1,'[]')",
                (key, "a" * 64, handler),
            )
            self.db.execute(
                "INSERT INTO step_receipts VALUES(?,'parse',?,?,'running',1,1)",
                (key, "a" * 64, (AT + timedelta(days=1)).isoformat()),
            )
        else:
            self.db.execute(
                "INSERT INTO review_slots VALUES(?,?)",
                (key, json.dumps({"state": "preparing" if active else "blocked"})),
            )
        return key

    def activate(self, number):
        if self.kind == "worker":
            self.db.execute(
                "UPDATE operations SET state='cancel_requested' WHERE id=?", (identity(number),)
            )
        else:
            self.db.execute(
                "UPDATE review_slots SET pending_intent=? WHERE bid_id=?",
                (json.dumps({"state": "preparing"}), identity(number)),
            )

    def remove(self, number):
        if self.kind == "worker":
            self.db.execute("DELETE FROM operations WHERE id=?", (identity(number),))
        else:
            self.db.execute("DELETE FROM review_slots WHERE bid_id=?", (identity(number),))

    @contextmanager
    def connection(self, *_):
        yield self

    def execute(self, query, params=()):
        if isinstance(query, sql.Composable):
            query = query.as_string()
        if query.startswith("SELECT design.lock_worker_bid"):
            self.observe(params[0])
            return self.Result([])
        query = re.sub(r"::(?:jsonb|uuid|text)", "", query)
        query = query.replace(" FOR UPDATE OF p", "").replace(" FOR UPDATE", "")
        query = query.replace("=ANY(%s)", " IN (%s)")
        values = []
        for value in params:
            if isinstance(value, list):
                query = query.replace("%s", ",".join("?" for _ in value), 1)
                values.extend(value)
            else:
                query = query.replace("%s", "?", 1)
                values.append(json.dumps(value.obj) if isinstance(value, Jsonb) else value)
        rows = [dict(row) for row in self.db.execute(query, values).fetchall()]
        for row in rows:
            if row.get("lease_until"):
                row["lease_until"] = datetime.fromisoformat(row["lease_until"])
        return self.Result(rows)

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    def run(self, cycles=3, between=lambda _: None, *, once=False):
        self.stop = LoopStop(cycles, between)
        self.monkeypatch.setattr(self.module, "STOP", self.stop)
        if self.kind == "worker":
            engine.reconcile(once=once)
        else:
            review_coordinator.run(once=once)


@pytest.fixture(params=["worker", "review"])
def world(request, monkeypatch):
    world = SweepWorld(request.param, monkeypatch)
    yield world
    world.db.close()


def test_busy_first_page_cannot_starve_later_cancellation_or_preparation(world):
    for number in range(1, 101):
        world.add(number)
    target = world.add(101, cancel=True)

    world.run(cycles=2)

    assert target in {key for _, key in world.visited}
    assert max(sum(cycle == n for cycle, _ in world.visited) for n in (0, 1)) <= 100
    if world.kind == "worker":
        assert (
            world.db.execute("SELECT state FROM operations WHERE id=?", (target,)).fetchone()[0]
            == "cancelled"
        )


def test_late_older_eligible_row_is_revisited_despite_continuous_new_arrivals(world):
    late = world.add(0, created=0, active=False)
    for number in range(1, 102):
        world.add(number)

    def arrivals(cycle):
        if cycle == 1:
            world.activate(0)
        for number in range(1000 + cycle * 200, 1200 + cycle * 200):
            world.add(number)

    world.run(cycles=3, between=arrivals)

    assert late in {key for _, key in world.visited}
    assert {identity(n) for n in range(1, 102)} <= {key for _, key in world.visited}


def test_equal_created_at_uses_identity_tie_breaker_and_visits_every_row(world):
    for number in range(200, 0, -1):
        world.add(number, created=1)

    world.run(cycles=2)

    assert [key for _, key in world.visited] == [identity(n) for n in range(1, 201)]


def test_deleted_sweep_end_does_not_prevent_wraparound(world):
    late = world.add(0, active=False)
    for number in range(1, 102):
        world.add(number)

    def change(cycle):
        if cycle == 1:
            world.remove(101)
            world.activate(0)

    world.run(cycles=3, between=change)

    assert late in {key for _, key in world.visited}


def test_once_remains_one_bounded_page(world):
    for number in range(1, 202):
        world.add(number)

    world.run(once=True)

    assert len(world.visited) == 100
    assert world.stop.cycles == 0


def test_worker_still_excludes_research_and_scoring_lanes(monkeypatch):
    world = SweepWorld("worker", monkeypatch)
    try:
        excluded = {world.add(1, handler="research/1"), world.add(2, handler="score/1")}
        ordinary = world.add(3)
        world.run(cycles=2)
        assert ordinary in {key for _, key in world.visited}
        assert not excluded.intersection(key for _, key in world.visited)
    finally:
        world.db.close()
