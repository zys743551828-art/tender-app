"""Fresh full ordered installation and previously unenumerated runtime ACL quarantine."""

import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from extended_recovery_helpers import proof
from psycopg import sql
from psycopg.conninfo import make_conninfo

from deploy import ci_checks, completion_recovery, extended_recovery, extended_recovery_runtime
from deploy.application_recovery import archive as definitions
from deploy.backups import generic, run

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_EXTENDED_RECOVERY_PG") != "1",
    reason="explicit disposable extended recovery PG/S3 required",
)


@pytest.mark.parametrize("fault", ["none", "audit_failure", "new_global_write_reader"])
def test_fresh_full_order_and_future_column_function_sequence_grantee_quarantine(
    monkeypatch, fault
):
    admin_dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    plan = extended_recovery.frozen_plan()
    database = "extended_plan_" + uuid4().hex
    group, login, reader = ("extended_" + uuid4().hex[:20] for _ in range(3))
    password = secrets.token_urlsafe(36)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        initial_roles = [
            r[0] for r in admin.execute("SELECT rolname FROM pg_roles ORDER BY rolname").fetchall()
        ]
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
        )
        try:
            with psycopg.connect(
                make_conninfo(admin_dsn, dbname=database), autocommit=True
            ) as owner:
                for item in plan:
                    owner.execute(item.content.decode())
                owner.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
                for name in (login, reader):
                    owner.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                        ).format(sql.Identifier(name), sql.Literal(password))
                    )
                owner.execute(
                    sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login))
                )
                owner.execute(
                    "CREATE SCHEMA future_recovery_probe; CREATE TABLE future_recovery_probe.rows(id int GENERATED ALWAYS AS IDENTITY, value text); CREATE FUNCTION future_recovery_probe.change() RETURNS void LANGUAGE sql SECURITY DEFINER AS 'INSERT INTO future_recovery_probe.rows(value) VALUES(''probe'')'; REVOKE ALL ON FUNCTION future_recovery_probe.change() FROM PUBLIC"
                )
                owner.execute(
                    sql.SQL(
                        "GRANT USAGE ON SCHEMA future_recovery_probe TO {}; GRANT UPDATE(value) ON future_recovery_probe.rows TO {}; GRANT EXECUTE ON FUNCTION future_recovery_probe.change() TO {}; GRANT USAGE ON ALL SEQUENCES IN SCHEMA future_recovery_probe TO {}"
                    ).format(*[sql.Identifier(group)] * 4)
                )
                role_evidence = extended_recovery._role_evidence(owner, owner.info.user)
                roles = [r[0] for r in role_evidence["runtime_roles"]]
                assert group in roles and login in roles
                description = generic.catalog(owner)
                assert extended_recovery.privilege_violations(
                    owner, [login], description["schemas"], reader=reader
                )
                owner.execute(
                    sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(database)
                    )
                )
                if fault == "new_global_write_reader":
                    assert reader not in roles
                    owner.execute(
                        sql.SQL("GRANT pg_write_all_data TO {}").format(sql.Identifier(reader))
                    )
                    before = definitions.detail(
                        owner, {"accounts": {"owner": {"user": owner.info.user}}}
                    )
                    assert owner.execute(
                        "SELECT pg_has_role(%s,'pg_write_all_data','MEMBER')", (reader,)
                    ).fetchone() == (True,)
                    with pytest.raises(run.BackupError, match="READER_NOT_RESTRICTED"):
                        extended_recovery.quarantine(owner, description, roles, database, reader)
                    assert (
                        definitions.detail(
                            owner, {"accounts": {"owner": {"user": owner.info.user}}}
                        )
                        == before
                    )
                    assert owner.execute(
                        "SELECT has_database_privilege(%s,current_database(),'CONNECT'),pg_has_role(%s,'pg_write_all_data','MEMBER')",
                        (reader, reader),
                    ).fetchone() == (False, True)
                    with pytest.raises(psycopg.Error):
                        psycopg.connect(
                            make_conninfo(
                                admin_dsn, dbname=database, user=reader, password=password
                            )
                        )
                    proof(
                        "reader-rejection",
                        {
                            "format": extended_recovery.FORMAT,
                            "new_reader_outside_snapshot_roles_checked": True,
                            "global_write_membership_rejected_without_repair": True,
                            "target_acl_unchanged_and_connect_denied": True,
                        },
                    )
                    return
                if fault == "audit_failure":
                    observed = definitions.detail(
                        owner, {"accounts": {"owner": {"user": owner.info.user}}}
                    )
                    with monkeypatch.context() as patch:
                        patch.setattr(
                            extended_recovery,
                            "privilege_violations",
                            lambda *args, **kwargs: {login: [1]},
                        )
                        with pytest.raises(run.BackupError, match="QUARANTINE_INCOMPLETE"):
                            extended_recovery.quarantine(
                                owner, description, roles, database, reader
                            )
                    assert (
                        definitions.detail(
                            owner, {"accounts": {"owner": {"user": owner.info.user}}}
                        )
                        == observed
                    )
                    assert owner.execute(
                        "SELECT has_database_privilege(%s,current_database(),'CONNECT')", (reader,)
                    ).fetchone() == (False,)
                    with pytest.raises(psycopg.Error):
                        psycopg.connect(
                            make_conninfo(
                                admin_dsn, dbname=database, user=reader, password=password
                            )
                        )
                extended_recovery.quarantine(owner, description, roles, database, reader)
                assert not extended_recovery.privilege_violations(
                    owner, roles, description["schemas"], reader=reader
                )
                with psycopg.connect(
                    make_conninfo(
                        admin_dsn,
                        dbname=database,
                        user=reader,
                        password=password,
                        options="-c default_transaction_read_only=off",
                    )
                ) as c:
                    assert c.execute(
                        "SELECT count(*) FROM future_recovery_probe.rows"
                    ).fetchone() == (0,)
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        c.execute("SELECT future_recovery_probe.change()")
                with pytest.raises(psycopg.Error):
                    psycopg.connect(
                        make_conninfo(admin_dsn, dbname=database, user=login, password=password)
                    )
                proof(
                    "schema",
                    {
                        "format": extended_recovery.FORMAT,
                        "ordered_sql": completion_recovery.plan_receipt(plan),
                        "tables": len(description["relations"]),
                        "schemas": description["schemas"],
                        "future_unlisted_direct_and_inherited_role_quarantined": True,
                        "column_update_sequence_usage_and_security_definer_execute_revoked": True,
                        "all_ordered_sql_installed_on_fresh_database": True,
                        "injected_late_audit_failure_rolls_back_without_connect_grant": fault
                        == "audit_failure",
                        "full_application_restore_qualified": False,
                    },
                )
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(database)))
            created_roles = [
                r[0]
                for r in admin.execute(
                    "SELECT rolname FROM pg_roles WHERE NOT rolname=ANY(%s) ORDER BY rolname",
                    (initial_roles,),
                ).fetchall()
            ]
            for name in created_roles:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def test_start_report_failure_after_actual_postmaster_start_still_stops_owned_cluster(monkeypatch):
    original = subprocess.run
    observed = []

    def faulty_start(arguments, **kwargs):
        result = original(arguments, **kwargs)
        if (
            Path(arguments[0]).name == "pg_ctl"
            and arguments[-1] == "start"
            and result.returncode == 0
        ):
            observed.append(Path(arguments[arguments.index("-D") + 1]).parent)
            return subprocess.CompletedProcess(
                arguments, 1, b"", b"synthetic lost startup completion"
            )
        return result

    cleanup = []
    monkeypatch.setattr(extended_recovery_runtime.subprocess, "run", faulty_start)
    library = os.environ.get("FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR")
    with pytest.raises(run.BackupError, match="NATIVE_PROCESS_FAILED"):
        with extended_recovery_runtime.temporary_postgres(
            Path(os.environ["FUSION_EXTENDED_RECOVERY_PG_BIN"]),
            Path(library) if library else None,
            ci_checks.test_environment(),
            cleanup,
        ):
            pytest.fail("the injected startup result must fail")
    assert len(observed) == 1 and not observed[0].exists()
    assert cleanup == [
        {
            "postgres_stopped": True,
            "listener_closed": True,
            "private_cluster_and_password_removed": True,
        }
    ]
