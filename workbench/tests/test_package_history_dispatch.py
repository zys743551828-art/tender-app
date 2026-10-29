"""Queue bounds, cursor fairness and purpose isolation without a database or provider."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest

from deploy import package_history_dispatcher as cli
from packages.model_governance import package_history_dispatch as dispatch
from packages.model_governance.common import GovernanceError


def candidate(number):
    return {
        "job_id": str(UUID(int=number)),
        "generation": 1,
        "created_at": "2026-01-01T00:00:00.123456+00:00",
    }


@pytest.fixture
def queue(monkeypatch):
    calls = []
    values = []

    @contextmanager
    def connection(purpose):
        def execute(statement, arguments):
            calls.append((purpose, statement, arguments))
            return SimpleNamespace(fetchone=lambda: {"value": deepcopy(values)})

        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(dispatch.runtime, "connection", connection)
    monkeypatch.setattr(
        dispatch.runtime,
        "run",
        lambda purpose, identity, generation: {"job_id": str(identity), "state": "succeeded"},
    )
    return values, calls


def test_bounded_page_uses_only_the_selected_purpose_and_preserves_microseconds(queue):
    values, calls = queue
    values.extend([candidate(1), candidate(2)])
    cursor, result = dispatch.cycle("train", limit=2)
    assert result["completed"] == result["attempted"] == result["scanned"] == 2
    assert result["research_only"] and result["formal_eligibility"] == "unavailable"
    assert result["provider_requests"] == result["paid_calls"] == 0
    assert calls[0][0] == "train" and calls[0][2] == ("train", None, None, 2)
    assert cursor.created_at.microsecond == 123456
    values.clear()
    next_cursor, result = dispatch.cycle("train", after=cursor, limit=2)
    assert calls[1][2][1:3] == (cursor.created_at, cursor.job_id)
    assert next_cursor is None and result["attempted"] == 0


@pytest.mark.parametrize(
    "purpose,limit",
    [
        ("verify", 5),
        (None, 5),
        ({}, 5),
        ("train", True),
        ("train", 0),
        ("train", 21),
        ("train", 1.0),
    ],
)
def test_invalid_purpose_or_batch_never_connects(queue, purpose, limit):
    with pytest.raises(GovernanceError):
        dispatch.cycle(purpose, limit=limit)
    assert queue[1] == []


@pytest.mark.parametrize(
    "change",
    ["extra", "count", "reverse", "duplicate", "boolean", "naive", "invalid_uuid", "behind"],
)
def test_invalid_metadata_cannot_run_a_job(queue, monkeypatch, change):
    values, _ = queue
    values.extend([candidate(1), candidate(2)])
    after = None
    if change == "extra":
        values[0]["private_label"] = "forbidden"
    elif change == "count":
        values.append(candidate(3))
    elif change == "reverse":
        values.reverse()
    elif change == "duplicate":
        values[1] = candidate(1)
    elif change == "boolean":
        values[0]["generation"] = True
    elif change == "naive":
        values[0]["created_at"] = "2026-01-01T00:00:00"
    elif change == "invalid_uuid":
        values[0]["job_id"] = "invalid"
    else:
        after = dispatch.Cursor(datetime(2026, 1, 2, tzinfo=timezone.utc), UUID(int=1))
    monkeypatch.setattr(
        dispatch.runtime, "run", lambda *_: pytest.fail("invalid metadata executed")
    )
    with pytest.raises(GovernanceError):
        dispatch.cycle("train", after=after, limit=2)


def test_stale_head_advances_and_does_not_starve_the_next_candidate(queue, monkeypatch):
    queue[0].extend([candidate(1), candidate(2)])

    def run(purpose, identity, generation):
        if identity.int == 1:
            raise psycopg.errors.ObjectNotInPrerequisiteState("private content must not be logged")
        return {"job_id": str(identity), "state": "succeeded"}

    monkeypatch.setattr(dispatch.runtime, "run", run)
    cursor, result = dispatch.cycle("train", limit=2)
    assert [item["state"] for item in result["outcomes"]] == ["deferred", "completed"]
    assert cursor.job_id.int == 2
    assert "private" not in str(result)


def test_permission_failure_is_fatal_without_claiming_later_work(queue, monkeypatch):
    queue[0].extend([candidate(1), candidate(2)])
    attempted = []

    def run(*args):
        attempted.append(args)
        raise psycopg.errors.InsufficientPrivilege("private detail")

    monkeypatch.setattr(dispatch.runtime, "run", run)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        dispatch.cycle("train", limit=2)
    assert len(attempted) == 1


def test_graceful_stop_does_not_start_the_remaining_job(queue, monkeypatch):
    queue[0].extend([candidate(1), candidate(2)])
    stopped = Event()

    def run(purpose, identity, generation):
        stopped.set()
        return {"job_id": str(identity), "state": "succeeded"}

    monkeypatch.setattr(dispatch.runtime, "run", run)
    cursor, result = dispatch.cycle("train", limit=2, stopped=stopped)
    assert result["attempted"] == 1 and cursor.job_id.int == 1


@pytest.mark.parametrize(
    "flags",
    [
        ["--purpose", "verify"],
        ["--purpose", "train"],
        ["--purpose", "train", "--profile", "unused", "--batch-size", "21"],
        ["--purpose", "train", "--profile", "unused", "--cycles", "0"],
        ["--purpose", "train", "--profile", "unused", "--poll-seconds", "0"],
        ["--purpose", "train", "--profile", "unused", "--owned-child"],
    ],
)
def test_launcher_rejects_ambiguous_or_unbounded_arguments(flags):
    with pytest.raises(SystemExit):
        cli.arguments(flags)


def test_parent_passes_one_private_purpose_without_ambient_credentials(tmp_path, monkeypatch):
    import shlex

    profile = tmp_path / "train.env"
    profile.write_text(
        "PACKAGE_HISTORY_TRAIN_DSN=" + shlex.quote("dbname=synthetic user=trainer") + "\n"
    )
    profile.chmod(0o600)
    # Linux private-file semantics are separately exercised in the Compose suite.
    monkeypatch.setattr(
        "deploy.package_history_worker.environment",
        lambda path, purpose: {
            "PACKAGE_HISTORY_TRAIN_DSN": "isolated-only",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        },
    )

    def run(command, **kwargs):
        assert command[1] == "-I" and "--owned-child" in command
        assert "--profile" not in command and command[command.index("--purpose") + 1] == "train"
        assert set(kwargs["env"]) == {"PACKAGE_HISTORY_TRAIN_DSN", "LANG", "LC_ALL", "TZ"}
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    monkeypatch.setenv("OWNER_DATABASE_DSN", "must-not-inherit")
    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(["--purpose", "train", "--profile", str(profile)]) == 0
