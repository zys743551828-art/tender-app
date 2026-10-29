"""Operator path uses native job adapters; these mocks are not PG acceptance."""

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_judgment_jobs import sample

from packages.domain.review_identity import digest
from packages.model_governance import material_job_commands as commands
from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import sha

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "material_job_cli", ROOT / "deploy/material_job_command.py"
)
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def start():
    row = sample()
    d = row["document"]
    args = {
        "renewal_id": d["initial_renewal_id"],
        "expected_renewal_digest": d["initial_renewal_digest"],
        "profile_id": d["profile_id"],
        "expected_profile_digest": d["profile_digest"],
        "command_id": d["command_id"],
        "expected_method_digest": jobs.method_digest(),
    }
    d["job_method_digest"] = args["expected_method_digest"]
    row["digest"] = digest(d)
    return {"version": commands.VERSION, "operation": "start", "arguments": args}, row


def private(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return sha(path.read_bytes())


def test_fixed_request_uses_existing_native_start_validation_and_redacted_receipt(
    tmp_path, monkeypatch
):
    cmd, row = start()
    path = tmp_path / "request.json"
    pin = private(path, cmd)
    loaded = commands.load(path, pin)
    calls = []

    def native(connection, query, args, *, write, expected_method_digest, validate):
        assert query.startswith("SELECT material_judgment_job.start(") and write
        calls.append(args)
        return validate(deepcopy(row))

    monkeypatch.setattr(jobs, "_execute", native)
    first = commands.execute(None, loaded)
    assert commands.execute(None, loaded) == first
    assert calls[0] == calls[1]
    assert first["job_digest"] == row["digest"] and not first["execution_authorized"]
    assert "slots" not in first and "request_login" not in first and first["model_requests"] == 0
    private(path, cmd | {"execution_authorized": True})
    with pytest.raises(jobs.JudgmentJobError):
        commands.load(path, pin)


@pytest.mark.parametrize("fault", ["extra", "operation", "method", "id", "digest", "version"])
def test_closed_requests_reject_before_any_native_call(fault, monkeypatch):
    cmd, _ = start()
    if fault == "extra":
        cmd["arguments"]["execution_authorized"] = True
    if fault == "operation":
        cmd["operation"] = "execute_attempt"
    if fault == "method":
        cmd["arguments"]["expected_method_digest"] = "b" * 64
    if fault == "id":
        cmd["arguments"]["command_id"] = "../another"
    if fault == "digest":
        cmd["arguments"]["expected_renewal_digest"] = "unknown"
    if fault == "version":
        cmd["version"] = "material-job-command/2"
    monkeypatch.setattr(jobs, "start", lambda *_a, **_k: pytest.fail("must not reach native"))
    with pytest.raises(jobs.JudgmentJobError):
        commands.execute(None, cmd)


@pytest.mark.parametrize("fault", ["symlink", "public", "oversized", "duplicate"])
def test_private_file_boundaries(tmp_path, fault):
    cmd, _ = start()
    path = tmp_path / "request"
    private(path, cmd)
    if fault == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        path = link
    if fault == "public":
        path.chmod(0o644)
    if fault == "oversized":
        path.write_bytes(b" " * 16385)
    if fault == "duplicate":
        path.write_text('{"version":1,"version":2}')
    with pytest.raises((OSError, GovernanceError)):
        commands.load(path, sha(path.read_bytes()))


@pytest.mark.parametrize(
    "code",
    [
        "CURRENT_STATE_UNAVAILABLE",
        "BUDGET_INSUFFICIENT",
        "COMMAND_CONFLICT",
        "INDEPENDENT_LOGIN_REQUIRED",
        "NATIVE_METHOD_MISMATCH",
    ],
)
def test_native_refusal_is_never_retried_or_falls_back(code, monkeypatch):
    cmd, _ = start()
    calls = []

    def denied(*_a, **_k):
        calls.append(1)
        jobs.fail(code)

    monkeypatch.setattr(jobs, "_execute", denied)
    with pytest.raises(jobs.JudgmentJobError, match=code):
        commands.execute(None, cmd)
    assert len(calls) == 1


def test_ack_loss_repeats_original_identity_without_automatic_retry(monkeypatch):
    cmd, row = start()
    calls = []

    def native(_c, _q, args, *, validate, **_k):
        calls.append(args)
        if len(calls) == 1:
            raise OSError("lost ACK")
        return validate(row)

    monkeypatch.setattr(jobs, "_execute", native)
    with pytest.raises(OSError):
        commands.execute(None, cmd)
    assert len(calls) == 1
    assert commands.execute(None, cmd)["job_digest"] == row["digest"]
    assert calls[0] == calls[1]


def test_profile_environment_is_exact_and_does_not_inherit_provider(tmp_path, monkeypatch):
    path = tmp_path / "profile"
    private(path, {"MATERIAL_JOB_DSN": "postgresql://synthetic-only"})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-copy")
    assert cli.environment(path) == cli.BASE | {"MATERIAL_JOB_DSN": "postgresql://synthetic-only"}
    private(path, {"MATERIAL_JOB_DSN": "x", "DEEPSEEK_API_KEY": "denied"})
    with pytest.raises(ValueError):
        cli.environment(path)


def test_method_command_is_isolated_and_credential_free():
    run = subprocess.run(
        [sys.executable, str(ROOT / "deploy/material_job_command.py"), "--action", "method"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["method_digest"] == jobs.method_digest()


def test_child_error_is_redacted_and_does_not_claim_rollback(monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "environ", cli.BASE | {"MATERIAL_JOB_DSN": "secret"})
    monkeypatch.setattr(
        commands, "load", lambda *_a: (_ for _ in ()).throw(OSError("private-secret"))
    )
    args = SimpleNamespace(
        profile=None, action="submit", request="private", expected_request_digest="a" * 64
    )
    assert cli.child(args) == 2
    output = capsys.readouterr().out
    assert "private-secret" not in output and "UNCONFIRMED" in output


def test_read_and_refresh_reuse_native_identity_checks(monkeypatch):
    _, row = start()
    doc = row["document"]
    event = {
        "version": "material-judgment-evidence/1",
        "event_id": str(uuid4()),
        "job_id": doc["job_id"],
        "job_digest": row["digest"],
        "command_id": str(uuid4()),
        "revision": 2,
        "previous_revision": 1,
        "renewal_id": str(uuid4()),
        "renewal_digest": "b" * 64,
        "recorded_at": doc["recorded_at"],
        "recorded_by": doc["recorded_by"],
        "recorded_by_oid": doc["recorded_by_oid"],
    }
    envelope = {"document": event, "digest": digest(event)}
    current = dict.fromkeys(
        (
            "profile_current",
            "renewal_current",
            "request_current",
            "slots_intact",
            "software_preparation_current",
            "software_budget_sufficient",
        ),
        False,
    )
    current.update(
        dict.fromkeys(
            (
                "fee_ledger_reserved",
                "execution_authorized",
                "send_lease_granted",
                "atomic_snapshot_verified",
            ),
            False,
        )
    )
    current.update(observed_at=doc["recorded_at"], evidence_revision=2)

    def native(_c, query, _args, *, validate, **_k):
        return validate(
            {"record": row, "evidence": envelope, "current": current}
            if ".read(" in query
            else envelope
        )

    monkeypatch.setattr(jobs, "_execute", native)
    common = {
        "job_id": doc["job_id"],
        "expected_job_digest": row["digest"],
        "expected_method_digest": jobs.method_digest(),
    }
    cmd = {"version": commands.VERSION, "operation": "read", "arguments": common}
    assert commands.execute(None, cmd)["current"] == current
    with pytest.raises(jobs.JudgmentJobError):
        commands.execute(None, cmd | {"arguments": common | {"job_id": str(uuid4())}})
    args = common | {
        "renewal_id": event["renewal_id"],
        "expected_renewal_digest": event["renewal_digest"],
        "expected_revision": 1,
        "command_id": event["command_id"],
    }
    cmd = {"version": commands.VERSION, "operation": "refresh", "arguments": args}
    result = commands.execute(None, cmd)
    assert result["evidence_id"] == event["event_id"] and result["evidence_revision"] == 2
    for revision in (True, 0, 2):
        with pytest.raises(jobs.JudgmentJobError):
            commands.execute(None, cmd | {"arguments": args | {"expected_revision": revision}})
