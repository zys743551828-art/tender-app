"""Pure initialization-plan/CLI checks. No SQL or real database connection is executed."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from deploy import bootstrap_fresh as fresh
from deploy import initialize_database as initialize
from deploy import schema_plan


class EmptyDatabase:
    def __init__(self, *, exists=False):
        self.exists = exists
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, statement):
        self.statements.append(statement)
        return self

    def fetchone(self):
        return (self.exists,)

    def transaction(self):
        return nullcontext()


def configuration():
    return {
        "OWNER_DATABASE_DSN": "explicit-fake-owner-no-connection",
        **{
            role.upper()
            + "_DATABASE_DSN": f"postgresql://synthetic_{role}:synthetic@127.0.0.1:1/fake"
            for role in fresh.CAPABILITIES
        },
    }


def test_both_entry_points_share_one_tuple_and_dependency_order():
    assert initialize.BASE_SQL is fresh.BASE_SQL is schema_plan.BASE_SQL
    assert initialize.ROOT is fresh.ROOT is schema_plan.ROOT
    assert len(schema_plan.BASE_SQL) == len(set(schema_plan.BASE_SQL))
    positions = {name: index for index, name in enumerate(schema_plan.BASE_SQL)}
    required = [
        "packages/contracts/sql/core.sql",
        "packages/contracts/sql/domain.sql",
        "packages/contracts/sql/bid-packages.sql",
        "packages/identity/sql/stable-lot-identity.sql",
        "packages/contracts/sql/retrieval.sql",
        "packages/contracts/sql/worker-functions.sql",
        "packages/contracts/sql/bid-package-requirements.sql",
        "packages/contracts/sql/bid-package-review-inputs.sql",
        "packages/contracts/sql/roles.sql",
    ]
    assert [positions[name] for name in required] == sorted(positions[name] for name in required)
    for grant in (
        "deploy/sql/bid-package-runtime-grants.sql",
        "deploy/sql/bid-package-requirement-runtime-grants.sql",
        "deploy/sql/bid-package-review-input-runtime-grants.sql",
        "deploy/sql/vector-runtime-grants.sql",
        "deploy/sql/research-source-qualification.sql",
    ):
        assert positions[grant] > positions["packages/contracts/sql/roles.sql"]
    assert all("archive" not in Path(name).parts for name in schema_plan.BASE_SQL)
    assert "packages/assistant/sql/intent-budget.sql" not in schema_plan.BASE_SQL
    assert "deploy/sql/model-governance.sql" not in schema_plan.BASE_SQL


def test_existing_full_shared_plan_reaches_initializer_in_frozen_order(monkeypatch):
    database = EmptyDatabase()
    monkeypatch.setattr(initialize, "local_configuration", configuration)
    monkeypatch.setattr(initialize.psycopg, "connect", lambda *a, **kw: database)
    initialize.main([])
    expected = [
        (schema_plan.ROOT / name).read_bytes().decode("utf-8") for name in schema_plan.BASE_SQL
    ]
    assert database.statements[1 : 1 + len(expected)] == expected
    assert len(database.statements) == 1 + len(expected) + 4 * len(fresh.CAPABILITIES)


@pytest.mark.parametrize("failure", ["missing", "invalid_utf8"])
def test_missing_or_invalid_later_base_input_never_reads_config_or_connects(
    tmp_path, monkeypatch, failure
):
    monkeypatch.setattr(initialize, "ROOT", tmp_path)
    monkeypatch.setattr(initialize, "BASE_SQL", ("first.sql", "later.sql"))
    (tmp_path / "first.sql").write_bytes("SELECT '中文';".encode())
    if failure == "invalid_utf8":
        (tmp_path / "later.sql").write_bytes(b"\xff-not-utf8")

    def forbidden(*args, **kwargs):
        pytest.fail("all base bytes must validate before config or connection")

    monkeypatch.setattr(initialize, "local_configuration", forbidden)
    monkeypatch.setattr(initialize.psycopg, "connect", forbidden)
    error = FileNotFoundError if failure == "missing" else UnicodeDecodeError
    with pytest.raises(error):
        initialize.main([])


def test_utf8_bytes_are_frozen_before_connection_and_not_reread(tmp_path, monkeypatch):
    name = "original.sql"
    original = "-- 实际UTF8中文与换行\r\nSELECT '原值';\r\n"
    (tmp_path / name).write_bytes(original.encode("utf-8"))
    monkeypatch.setattr(initialize, "ROOT", tmp_path)
    monkeypatch.setattr(initialize, "BASE_SQL", (name,))
    monkeypatch.setattr(initialize, "local_configuration", configuration)
    database = EmptyDatabase()

    def connect(*args, **kwargs):
        (tmp_path / name).write_bytes(b"SELECT 'changed after connect';")
        return database

    monkeypatch.setattr(initialize.psycopg, "connect", connect)
    initialize.main([])
    assert database.statements[1] == original


def test_existing_design_schema_refuses_every_ddl_and_login(monkeypatch):
    database = EmptyDatabase(exists=True)
    monkeypatch.setattr(initialize, "local_configuration", configuration)
    monkeypatch.setattr(initialize.psycopg, "connect", lambda *a, **kw: database)
    with pytest.raises(SystemExit, match="design schema already exists"):
        initialize.main([])
    assert len(database.statements) == 1
    assert "SELECT EXISTS" in database.statements[0]


@pytest.mark.parametrize(
    "arguments,code",
    [
        (["--help"], 0),
        (["--reviewed-sql", "archive.sql", "0" * 64], 2),
        (["--extension-sql", "archive.sql"], 2),
        (["unexpected"], 2),
    ],
)
def test_initializer_cli_rejects_extensions_before_inputs_config_or_connect(
    tmp_path, monkeypatch, arguments, code
):
    monkeypatch.setattr(initialize, "ROOT", tmp_path)
    monkeypatch.setattr(initialize, "BASE_SQL", ("not-present.sql",))

    def forbidden(*args, **kwargs):
        pytest.fail("CLI help/invalid arguments cannot reach configuration or database")

    monkeypatch.setattr(initialize, "local_configuration", forbidden)
    monkeypatch.setattr(initialize.psycopg, "connect", forbidden)
    with pytest.raises(SystemExit) as error:
        initialize.main(arguments)
    assert error.value.code == code


def minimal_environment(tmp_path):
    return {
        **{key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ},
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "WORKBENCH_ENV_FILE": str(tmp_path / "never-read-business-profile.env"),
    }


@pytest.mark.parametrize("style", ["script", "module", "legacy_import"])
def test_original_direct_module_and_top_level_import_boundaries(tmp_path, style):
    if style == "script":
        args = [str(schema_plan.ROOT / "deploy/initialize_database.py"), "--help"]
        cwd = tmp_path
    elif style == "module":
        args = ["-m", "deploy.initialize_database", "--help"]
        cwd = schema_plan.ROOT
    else:
        args = [
            "-c",
            "import sys;sys.path.insert(0,sys.argv[1]);import initialize_database;print('legacy import ready')",
            str(schema_plan.ROOT / "deploy"),
        ]
        cwd = tmp_path
    result = subprocess.run(
        [sys.executable, "-X", "utf8", *args],
        cwd=cwd,
        env=minimal_environment(tmp_path),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert ("legacy import ready" if style == "legacy_import" else "usage:") in result.stdout
    assert "Initialized" not in result.stdout


def test_schema_plan_import_has_no_database_or_initializer_dependency(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            "import sys;import deploy.schema_plan;assert 'psycopg' not in sys.modules;assert 'deploy.initialize_database' not in sys.modules;assert 'deploy.bootstrap_fresh' not in sys.modules",
        ],
        cwd=schema_plan.ROOT,
        env=minimal_environment(tmp_path),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
