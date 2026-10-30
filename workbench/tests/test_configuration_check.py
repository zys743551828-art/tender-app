"""Real launcher processes with explicit synthetic profiles and no provider I/O."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deploy import configuration_check as config

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "synthetic-private-sentinel"


def profile(tmp_path, content):
    path = tmp_path / "input.env"
    path.write_text(content)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    "content", ["BROKEN_" + PRIVATE, "KEY='" + PRIVATE, "KEY=a\nKEY=b", "KEY=a b"]
)
def test_malformed_profile_has_safe_actionable_error(tmp_path, content):
    with pytest.raises(config.ConfigurationError) as error:
        config.load(profile(tmp_path, content))
    assert PRIVATE not in str(error.value)
    assert "ENV_" in str(error.value)


def test_missing_symlink_and_public_file_rejected(tmp_path):
    path = tmp_path / "missing"
    with pytest.raises(config.ConfigurationError, match="ENV_FILE_REQUIRED"):
        config.load(path)
    target = profile(tmp_path, "KEY=value")
    path.symlink_to(target)
    with pytest.raises(config.ConfigurationError, match="ENV_FILE_REQUIRED"):
        config.load(path)
    target.chmod(0o644)
    with pytest.raises(config.ConfigurationError, match="ENV_FILE_NOT_PRIVATE"):
        config.load(target)


def launch(path, code):
    return subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "deploy/run.py"),
            "--env-file",
            str(path),
            "--role",
            "api",
            "--",
            sys.executable,
            "-S",
            "-c",
            code,
        ],
        env={"PATH": os.defpath, "API_DATABASE_DSN": PRIVATE, "MODEL_DATABASE_DSN": PRIVATE},
        capture_output=True,
        text=True,
        check=False,
    )


def test_wrong_entry_rejected_before_command_even_with_inherited_dsn(tmp_path):
    result = launch(
        profile(tmp_path, "BIDWB_STORAGE_SECRET_ACCESS_KEY=" + PRIVATE),
        "raise AssertionError('must not run')",
    )
    assert result.returncode != 0 and "ENV_ENTRY_MISMATCH" in result.stderr
    assert PRIVATE not in result.stderr and "AssertionError" not in result.stderr
    with pytest.raises(config.ConfigurationError, match="ENV_ROLE_DSN_REQUIRED"):
        config.workbench(profile(tmp_path, "APP_ORIGIN=http://127.0.0.1"), "api")


def test_real_child_receives_fixed_role_and_no_owner_or_other_dsns(tmp_path):
    path = profile(
        tmp_path,
        "API_DATABASE_DSN=synthetic-api\nOWNER_DATABASE_DSN="
        + PRIVATE
        + "\nWORKER_DATABASE_DSN=synthetic-worker\nPOSTGRES_PASSWORD="
        + PRIVATE,
    )
    result = launch(
        path,
        "import os,json;print(json.dumps({k:v for k,v in os.environ.items() if k.endswith('_DATABASE_DSN') or k in ('WORKBENCH_RUNTIME_ROLE','POSTGRES_PASSWORD')}))",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "API_DATABASE_DSN": "synthetic-api",
        "WORKBENCH_RUNTIME_ROLE": "api",
    }
    assert PRIVATE not in result.stdout + result.stderr


def test_legacy_compose_reports_names_not_private_values(tmp_path):
    with pytest.raises(config.ConfigurationError, match="OSS_ENDPOINT_URL") as error:
        config.check(profile(tmp_path, "BIDWB_STORAGE_ENDPOINT_URL=" + PRIVATE), "legacy-compose")
    assert PRIVATE not in str(error.value)


def test_offline_cli_works_without_installed_dependencies(tmp_path):
    values = {
        "API_DATABASE_DSN": "synthetic",
        "APP_ORIGIN": "http://127.0.0.1",
        "SESSION_SECRET": PRIVATE,
        "CSRF_SECRET": PRIVATE,
        "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:1",
        "OBJECT_STORE_BACKEND": "s3",
        "OBJECT_STORE_ENDPOINT": "http://127.0.0.1:1",
        "OBJECT_STORE_BUCKET": "synthetic",
        "OBJECT_STORE_REGION": "us-east-1",
        "OBJECT_STORE_ACCESS_KEY": PRIVATE,
        "OBJECT_STORE_SECRET_KEY": PRIVATE,
    }
    path = profile(tmp_path, "\n".join(f"{key}={value}" for key, value in values.items()))
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "deploy/configuration_check.py"),
            "--entry",
            "workbench",
            "--env-file",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["passed"] and receipt["real_calls"] == 0
    assert PRIVATE not in result.stdout + result.stderr


def test_missing_file_does_not_launch_with_inherited_profile(tmp_path):
    result = launch(tmp_path / "missing", "raise AssertionError('must not run')")
    assert result.returncode != 0 and "ENV_FILE_REQUIRED" in result.stderr
    assert PRIVATE not in result.stderr and "AssertionError" not in result.stderr
