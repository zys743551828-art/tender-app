"""Opt-in isolated invocation of the existing native job CLI. Never a model call."""

import json
import os
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from packages.model_governance import material_job_commands as commands
from packages.storage.private_cas import sha

ROOT = Path(__file__).resolve().parents[2]
ENV = {"WORKBENCH_ENV_FILE": "/dev/null", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


def submit(command):
    try:
        commands.validate(command)
    except commands.jobs.JudgmentJobError:
        return "method_changed"
    profile = os.environ.get("MATERIAL_QUALIFIED_JOB_PROFILE")
    if not profile:
        return "not_configured"
    if not Path(profile).is_absolute():
        return "not_configured"
    # No API DSN, session secret or provider key is inherited. The established
    # CLI checks the private profile and owns a separate-purpose transaction.
    with tempfile.TemporaryDirectory(prefix="material-job-") as directory:
        path = Path(directory) / "command.json"
        raw = json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        argv = [
            sys.executable,
            "-I",
            str(ROOT / "deploy/material_job_command.py"),
            "--action",
            "submit",
            "--profile",
            profile,
            "--request",
            str(path),
            "--expected-request-digest",
            sha(raw),
        ]
        try:
            result = subprocess.run(
                argv, cwd=ROOT, env=ENV, capture_output=True, timeout=45, check=False
            )  # nosec B603
        except (OSError, subprocess.TimeoutExpired):
            return "unconfirmed"
        # stdout is not authority. Only the native atomic acceptance row can
        # confirm commit, including a lost ACK or a failed result validation.
        return "submitted" if result.returncode == 0 else "unconfirmed"
