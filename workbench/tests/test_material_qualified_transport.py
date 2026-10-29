"""Existing CLI isolation and exact command reuse; no native connection opened."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import material_qualified_job_transport as transport


def command():
    return {
        "version": "material-job-command/1",
        "operation": "start",
        "arguments": {
            "renewal_id": str(uuid4()),
            "expected_renewal_digest": "a" * 64,
            "profile_id": str(uuid4()),
            "expected_profile_digest": "b" * 64,
            "command_id": str(uuid4()),
            "expected_method_digest": jobs.method_digest(),
        },
    }


def test_disabled_default_never_spawns(monkeypatch):
    monkeypatch.delenv("MATERIAL_QUALIFIED_JOB_PROFILE", raising=False)
    monkeypatch.setattr(transport.subprocess, "run", lambda *_a, **_k: pytest.fail("spawned"))
    assert transport.submit(command()) == "not_configured"


def test_private_file_digest_and_environment_isolation(monkeypatch):
    monkeypatch.setenv("MATERIAL_QUALIFIED_JOB_PROFILE", "/private/existing-profile.json")
    monkeypatch.setenv("API_DATABASE_DSN", "not-for-child")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-for-child")
    original = command()
    paths = []

    def run(argv, **kwargs):
        assert argv[1] == "-I" and kwargs["env"] == transport.ENV
        path = Path(argv[argv.index("--request") + 1])
        paths.append(path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_bytes()) == original
        assert transport.sha(path.read_bytes()) == argv[-1]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(transport.subprocess, "run", run)
    assert transport.submit(original) == "submitted"
    assert all(not p.exists() for p in paths)


def test_timeout_is_uncertain_not_no_commit(monkeypatch):
    monkeypatch.setenv("MATERIAL_QUALIFIED_JOB_PROFILE", "/private/profile.json")

    def timeout(*_a, **_k):
        raise transport.subprocess.TimeoutExpired("hidden", 45)

    monkeypatch.setattr(transport.subprocess, "run", timeout)
    assert transport.submit(command()) == "unconfirmed"


def test_old_method_is_not_rebound(monkeypatch):
    value = command()
    value["arguments"]["expected_method_digest"] = "f" * 64
    monkeypatch.setattr(transport.subprocess, "run", lambda *_a, **_k: pytest.fail("spawned"))
    assert transport.submit(value) == "method_changed"
