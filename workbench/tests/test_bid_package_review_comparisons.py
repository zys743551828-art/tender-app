"""Read-only comparison snapshot and cursor boundaries, with explicit database ports."""
# ruff: noqa: F401,F811

from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_package_review_comparison import case, pair, report, rows, sync, uid

from packages.contracts.package_review_comparisons_api import valid
from packages.domain import bid_package_review_comparisons as service
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha
from packages.identity import pagination


@pytest.fixture
def reader(pair, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "synthetic-comparison-cursor-secret")
    for side in pair:
        original = deepcopy(rows(side)[0])
        rows(side)[:] = [original | {"requirement_id": uid(200 + i)} for i in range(3)]
        sync(side)
    state = {"pair": pair, "events": [], "opens": 0}

    class Cursor:
        def __init__(self, values):
            self.values = values

        def fetchall(self):
            return self.values

    class Connection:
        def __init__(self):
            self.snapshot = deepcopy(state["pair"])
            self.read_only = False

        def execute(self, sql, parameters=()):
            state["events"].append((sql, parameters))
            if sql == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY":
                self.read_only = True
                return Cursor([])
            assert self.read_only and sql.startswith(service.runs.SELECT)
            bid, left, right = parameters
            return Cursor(
                [
                    {
                        "run": side["run"],
                        "input_manifest": side["input"]["manifest"],
                        "input_digest": side["input"]["digest"],
                    }
                    for side in reversed(self.snapshot)
                    if side["run"]["scope"]["bid_id"] == bid and side["run"]["id"] in (left, right)
                ]
            )

    @contextmanager
    def connection(worker=False):
        assert worker is False
        state["opens"] += 1
        yield Connection()

    def current(c, run):
        assert c.read_only
        state["events"].append(("read-current-heads", run["id"]))
        return next(side["human"] for side in c.snapshot if side["run"]["id"] == run["id"])

    monkeypatch.setattr(service, "connection", connection)
    monkeypatch.setattr(service.runs, "view", lambda row: deepcopy(row["run"]))
    monkeypatch.setattr(service.decisions, "current", current)
    state["args"] = (
        pair[0]["run"]["scope"]["bid_id"],
        pair[0]["run"]["id"],
        pair[1]["run"]["id"],
    )
    return state


def test_bounded_pages_use_one_read_only_snapshot_and_exact_ordered_run_pair(reader):
    first = service.read(*reader["args"], limit=2)
    second = service.read(*reader["args"], limit=2, cursor=first["next_cursor"])
    assert valid("PackageReviewComparisonPage", first)
    assert valid("PackageReviewComparisonPage", second)
    assert first["left"]["id"] == reader["args"][1]
    assert first["right"]["id"] == reader["args"][2]
    assert first["has_more"] and not second["has_more"] and second["next_cursor"] is None
    assert first["comparison_digest"] == second["comparison_digest"]
    assert first["counts"] == second["counts"] and first["counts"]["unchanged"] == 3
    assert [row["requirement_id"] for row in first["items"] + second["items"]] == [
        uid(200),
        uid(201),
        uid(202),
    ]
    assert reader["opens"] == 2
    assert sum(sql.startswith("SET TRANSACTION") for sql, _ in reader["events"]) == 2
    assert not any(
        "INSERT" in sql or "UPDATE" in sql or "FOR " in sql for sql, _ in reader["events"]
    )


@pytest.mark.parametrize("mutation", ["human", "swapped", "tampered", "unknown_position"])
def test_cursor_cannot_mix_human_snapshots_run_direction_or_unseen_rows(reader, mutation):
    first = service.read(*reader["args"], limit=1)
    args, cursor = reader["args"], first["next_cursor"]
    if mutation == "human":
        reader["pair"][1]["human"]["items"][0]["current"] = {
            "id": uid(500),
            "digest": "0" * 64,
            "sequence_no": 1,
            "actor_id": uid(501),
            "created_at": "2026-10-21T03:00:00.000000Z",
            "state": "needs_review",
            "reason": "新的人工复查意见",
        }
    elif mutation == "swapped":
        args = (args[0], args[2], args[1])
    elif mutation == "tampered":
        cursor += "x"
    else:
        marker = sha(
            {
                "directory": "package-review-comparison/1",
                "comparison_digest": first["comparison_digest"],
            }
        )
        cursor = pagination.encode(marker, ["", uid(999)])
    with pytest.raises(DomainError) as error:
        service.read(*args, limit=1, cursor=cursor)
    assert error.value.code == "INVALID_CURSOR" and error.value.status == 422


@pytest.mark.parametrize("mutation", ["foreign_bid", "missing_run", "pending"])
def test_unavailable_run_pair_never_returns_partial_comparison(reader, mutation):
    args = reader["args"]
    if mutation == "foreign_bid":
        args = (uid(999), *args[1:])
    elif mutation == "missing_run":
        args = (*args[:2], uid(999))
    else:
        run = reader["pair"][1]["run"]
        run["operation"]["state"], run["result"] = "queued", None
    with pytest.raises(DomainError) as error:
        service.read(*args)
    assert error.value.code == (
        "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED"
        if mutation == "pending"
        else "PACKAGE_REVIEW_COMPARISON_RUN_NOT_FOUND"
    )


@pytest.mark.parametrize("limit", [0, 101, True, "1"])
def test_invalid_page_size_is_rejected_before_database_access(reader, limit):
    with pytest.raises(DomainError) as error:
        service.read(*reader["args"], limit=limit)
    assert error.value.code == "PACKAGE_REVIEW_COMPARISON_REQUEST_INVALID"
    assert reader["opens"] == 0
