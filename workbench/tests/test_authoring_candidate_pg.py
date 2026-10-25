"""Real fresh bootstrap and effective ACL checks on an explicit disposable PG17."""

import json
import os
import subprocess  # nosec B404
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from deploy import authoring_candidate as candidate
from deploy import bootstrap_fresh as fresh
from deploy.initialize_database import file_configuration

ADMIN_DSN = os.environ.get("FUSION_AUTHORING_CANDIDATE_ADMIN_DSN")
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not ADMIN_DSN or os.environ.get("FUSION_AUTHORING_CANDIDATE_PG") != "1",
    reason="requires explicit disposable authoring-candidate PG17 with SCRAM logins",
)


@pytest.fixture(scope="module")
def isolated(tmp_path_factory):
    assert ADMIN_DSN is not None
    fields = conninfo_to_dict(ADMIN_DSN)
    assert fields["host"] == "127.0.0.1" and fields["dbname"] == "postgres" and fields["password"]
    directory = tmp_path_factory.mktemp("authoring-candidate-native")
    directory.chmod(0o700)
    source = directory / "repository"
    for relative in (*fresh.BASE_SQL, *candidate.OPTIONAL_SQL):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    base = directory / "base.env"
    fresh.write_private(
        base,
        {
            "OWNER_DATABASE_DSN": fresh.identity_dsn(fields, database="postgres"),
            "OBJECT_STORE_PREFIX": "synthetic-authoring-candidate/",
            "APP_ORIGIN": "http://127.0.0.1:5191",
        },
    )
    creations = []
    groups = (*fresh.GROUPS, "tender_assistant_budget_admin")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        assert admin.info.server_version // 10000 == 17
        assert (
            admin.execute(
                "SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)", (list(groups),)
            ).fetchall()
            == []
        )
        for group in fresh.GROUPS:
            admin.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(group))
            )
        try:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(fresh, "ROOT", source)
                yield {"admin": admin, "base": base, "directory": directory, "creations": creations}
        finally:
            for name, root in creations:
                database = "tender_checks_" + name
                logins = admin.execute(
                    "SELECT rolname FROM pg_roles WHERE starts_with(rolname,%s)",
                    ("twb_checks_" + name + "_",),
                ).fetchall()
                if admin.execute(
                    "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
                ).fetchone():
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(database))
                    )
                for (login,) in logins:
                    admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))
                for kind in ("checks", "init"):
                    (root / ".local" / (name + "-" + kind + ".env")).unlink(missing_ok=True)
            for group in reversed(groups):
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(group)))


def name_for(isolated, root=None):
    name = "ac_" + uuid4().hex[:12]
    isolated["creations"].append((name, root or fresh.ROOT))
    return name


def invoke(isolated, document, name):
    plan_file = isolated["directory"] / (name + ".json")
    plan_file.write_text(json.dumps(document), encoding="utf-8")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    env["WORKBENCH_ENV_FILE"] = "explicit-authoring-candidate-no-business-profile"
    env["AUTHORING_CANDIDATE_TEST_ROOT"] = str(fresh.ROOT)
    # Only the fixture filesystem is redirected. The actual argument parser,
    # plan checker, bootstrap and independently authenticated ACL checks run.
    program = (
        "import os; from pathlib import Path; from deploy import bootstrap_fresh as fresh; "
        "fresh.ROOT=Path(os.environ.pop('AUTHORING_CANDIDATE_TEST_ROOT')); "
        "from deploy.create_check_environment import main; main()"
    )
    return subprocess.run(  # nosec B603
        [
            sys.executable,
            "-c",
            program,
            "--base-init-file",
            str(isolated["base"]),
            "--name",
            name,
            "--authoring-candidate",
            str(plan_file),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


@pytest.fixture(scope="module")
def installed(isolated):
    document = candidate.plan()
    name = name_for(isolated)
    process = invoke(isolated, document, name)
    assert process.returncode == 0, (
        "native authoring bootstrap failed; inspect the private initialization profile"
    )
    result = json.loads(process.stdout)
    return result, document


def test_actual_creation_entry_consumes_plan_and_independent_runtime_permissions(
    isolated, installed
):
    result, document = installed
    assert [item["path"] for item in result["ordered_sql"]] == [
        *fresh.BASE_SQL,
        *candidate.OPTIONAL_SQL,
    ]
    assert result["ordered_sql"][-8:] == document["optional_sql"]
    receipt = result["authoring_candidate"]
    assert receipt["plan_digest"] == document["digest"] and receipt["schema_permissions_verified"]
    assert not receipt["business_workflow_executed"] and result["no_business_process_started"]
    assert result["logins"]["api"] != result["logins"]["worker"]
    profile = fresh.ROOT / result["profiles"]["business"]
    assert profile.stat().st_mode & 0o777 == 0o600
    values = file_configuration(profile)
    assert "OWNER_DATABASE_DSN" not in values and not values["KAFKA_BOOTSTRAP_SERVERS"]
    with psycopg.connect(values["API_DATABASE_DSN"], autocommit=True) as api:
        assert api.execute(
            "SELECT count(*) FROM design.authoring_exact_revision_records"
        ).fetchone() == (0,)
        assert api.execute("SELECT count(*) FROM design.assistant_price_versions").fetchone() == (
            0,
        )
        assert api.execute("SELECT count(*) FROM design.assistant_budget_versions").fetchone() == (
            0,
        )
        assert api.execute("SELECT count(*) FROM design.outbox").fetchone() == (0,)
        assert api.execute(
            "SELECT to_regnamespace('material_execution'),to_regnamespace('package_historical_research')"
        ).fetchone() == (None, None)
    with psycopg.connect(values["WORKER_DATABASE_DSN"], autocommit=True) as worker:
        for relation in ("authoring_exact_manual_revisions", "authoring_exact_revision_records"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute(
                    sql.SQL("SELECT * FROM design.{} LIMIT 0").format(sql.Identifier(relation))
                )
    if evidence := os.environ.get("FUSION_AUTHORING_CANDIDATE_EVIDENCE"):
        Path(evidence).mkdir(parents=True, exist_ok=True)
        (Path(evidence) / "native-receipt.json").write_text(json.dumps(result, indent=2) + "\n")


@pytest.mark.parametrize("change", ("missing", "reordered", "sha"))
def test_actual_entry_refuses_invalid_plan_without_creating_database(isolated, change):
    document = deepcopy(candidate.plan())
    if change == "missing":
        document["optional_sql"].pop()
    elif change == "reordered":
        document["optional_sql"][-2:] = reversed(document["optional_sql"][-2:])
    else:
        document["optional_sql"][-1]["sha256"] = "0" * 64
    document["digest"] = candidate.digest(
        {key: value for key, value in document.items() if key != "digest"}
    )
    name = name_for(isolated)
    process = invoke(isolated, document, name)
    assert process.returncode == 1
    assert json.loads(process.stderr)["code"] in {
        "AUTHORING_CANDIDATE_PLAN_INVALID",
        "REVIEWED_SQL_DIGEST_MISMATCH",
    }
    assert (
        not isolated["admin"]
        .execute("SELECT 1 FROM pg_database WHERE datname=%s", ("tender_checks_" + name,))
        .fetchone()
    )
    assert not (fresh.ROOT / ".local" / (name + "-init.env")).exists()


@pytest.mark.parametrize("relative", (candidate.OPTIONAL_SQL[-1], fresh.BASE_SQL[0]))
def test_changed_source_file_refuses_before_real_cluster_mutation(
    isolated, tmp_path, monkeypatch, relative
):
    original = fresh.ROOT
    for relative in (*fresh.BASE_SQL, *candidate.OPTIONAL_SQL):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((original / relative).read_bytes())
    monkeypatch.setattr(fresh, "ROOT", tmp_path)
    document = candidate.plan()
    changed = tmp_path / relative
    changed.write_bytes(changed.read_bytes() + b"\n-- explicit synthetic changed input\n")
    name = name_for(isolated, tmp_path)
    with pytest.raises(fresh.BootstrapError, match="REVIEWED_SQL_DIGEST_MISMATCH"):
        candidate.create(document, base_profile=isolated["base"], name=name)
    assert (
        not isolated["admin"]
        .execute("SELECT 1 FROM pg_database WHERE datname=%s", ("tender_checks_" + name,))
        .fetchone()
    )


def test_existing_database_is_refused_and_never_migrated(isolated):
    name = name_for(isolated)
    database = "tender_checks_" + name
    isolated["admin"].execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
    )
    with psycopg.connect(make_conninfo(ADMIN_DSN, dbname=database), autocommit=True) as owner:
        owner.execute("CREATE TABLE public.candidate_marker(value text)")
        owner.execute("INSERT INTO public.candidate_marker VALUES('must remain unchanged')")
        process = invoke(isolated, candidate.plan(), name)
        assert process.returncode == 1
        assert json.loads(process.stderr)["code"] == "REFUSING_EXISTING_DATABASE"
        assert owner.execute("SELECT value FROM public.candidate_marker").fetchall() == [
            ("must remain unchanged",)
        ]
        assert owner.execute("SELECT to_regnamespace('design')").fetchone() == (None,)
    assert not (fresh.ROOT / ".local" / (name + "-init.env")).exists()


@pytest.mark.parametrize(
    "grant,revoke,error",
    (
        (
            "GRANT SELECT ON design.authoring_exact_manual_revisions TO PUBLIC",
            "REVOKE SELECT ON design.authoring_exact_manual_revisions FROM PUBLIC",
            "TABLE_PRIVILEGE_MISMATCH",
        ),
        (
            "GRANT SELECT(id) ON design.authoring_exact_manual_revisions TO tender_worker",
            "REVOKE SELECT(id) ON design.authoring_exact_manual_revisions FROM tender_worker",
            "TABLE_PRIVILEGE_MISMATCH",
        ),
        (
            "GRANT UPDATE ON design.authoring_exact_manual_revisions TO tender_api",
            "REVOKE UPDATE ON design.authoring_exact_manual_revisions FROM tender_api",
            "TABLE_PRIVILEGE_MISMATCH",
        ),
        (
            "GRANT EXECUTE ON FUNCTION design.authoring_exact_check_manual_revision(uuid) TO tender_api",
            "REVOKE EXECUTE ON FUNCTION design.authoring_exact_check_manual_revision(uuid) FROM tender_api",
            "FUNCTION_PRIVILEGE_MISMATCH",
        ),
        (
            "GRANT tender_api TO tender_worker",
            "REVOKE tender_api FROM tender_worker",
            "MEMBERSHIP_NOT_EXACT",
        ),
        (
            "GRANT CREATE ON SCHEMA design TO tender_worker",
            "REVOKE CREATE ON SCHEMA design FROM tender_worker",
            "OWNER_OR_CREATE_PRIVILEGE",
        ),
    ),
)
def test_actual_effective_acl_pollution_is_detected_without_repair(installed, grant, revoke, error):
    result, document = installed
    with psycopg.connect(
        make_conninfo(ADMIN_DSN, dbname=result["database"]), autocommit=True
    ) as owner:
        owner.execute(grant)
        try:
            with pytest.raises(fresh.BootstrapError, match=error):
                candidate.verify(result, candidate.checked(document))
        finally:
            owner.execute(revoke)


def test_failed_created_acl_withholds_business_profile_and_keeps_private_recovery(
    isolated, monkeypatch
):
    original = candidate.verify
    name = name_for(isolated)

    def polluted(result, entries):
        with psycopg.connect(
            make_conninfo(ADMIN_DSN, dbname=result["database"]), autocommit=True
        ) as owner:
            owner.execute("GRANT SELECT ON design.authoring_exact_manual_revisions TO PUBLIC")
        return original(result, entries)

    monkeypatch.setattr(candidate, "verify", polluted)
    with pytest.raises(fresh.BootstrapError, match="TABLE_PRIVILEGE_MISMATCH"):
        candidate.create(candidate.plan(), base_profile=isolated["base"], name=name)
    assert (fresh.ROOT / ".local" / (name + "-init.env")).stat().st_mode & 0o777 == 0o600
    assert not (fresh.ROOT / ".local" / (name + "-checks.env")).exists()
