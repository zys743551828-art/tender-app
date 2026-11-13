"""B7 install ordering must not overwrite a working B5 validator."""

# ruff: noqa: F401,F811
import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN
from authoring_package_job_fixtures import database as job_database
from authoring_package_job_fixtures import input_database
from test_authoring_exact_builds_pg import database as build_database
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_exact_text_edits_pg import database as single_database

from packages.authoring import exact_marked_text_edits, exact_text_edits
from packages.domain.runtime import ROOT, connection

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated native B5 PG17")


@pytest.fixture(scope="module")
def database(single_database):
    return single_database


def test_b7_requires_b6_without_modifying_b5_then_installs_privately(database):
    owner = database["owner"]
    original = owner.execute(
        "SELECT pg_get_functiondef('design.authoring_exact_check_manual_record(uuid)'::regprocedure) AS definition"
    ).fetchone()["definition"]
    with connection() as c:
        assert exact_text_edits.available(c)
        assert not exact_marked_text_edits.available(c)
    b7 = (ROOT / "packages/contracts/sql/authoring-exact-marked-text-edits.sql").read_text()
    try:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="REQUIRES_B6"):
            owner.execute(b7)
    finally:
        # The migration starts a transaction explicitly; clear its aborted state.
        owner.execute("ROLLBACK")
    assert (
        owner.execute(
            "SELECT pg_get_functiondef('design.authoring_exact_check_manual_record(uuid)'::regprocedure) AS definition"
        ).fetchone()["definition"]
        == original
    )
    assert (
        owner.execute(
            "SELECT to_regprocedure('design.authoring_exact_check_marked_text_record(uuid)') AS value"
        ).fetchone()["value"]
        is None
    )
    with connection() as c:
        assert exact_text_edits.available(c)
        assert not exact_marked_text_edits.available(c)
    owner.execute(
        (ROOT / "packages/contracts/sql/authoring-exact-multi-text-edits.sql").read_text()
    )
    owner.execute(b7)
    assert (
        owner.execute(
            "SELECT pg_get_functiondef('design.authoring_exact_check_single_text_record(uuid)'::regprocedure) AS definition"
        )
        .fetchone()["definition"]
        .replace("authoring_exact_check_single_text_record", "authoring_exact_check_manual_record")
        == original
    )
    for worker in (False, True):
        with connection(worker) as c:
            for name in ("single", "multi", "marked"):
                assert not c.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE') AS granted",
                    (f"design.authoring_exact_check_{name}_text_record(uuid)",),
                ).fetchone()["granted"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection(worker) as c:
                c.execute("SELECT design.authoring_exact_check_marked_text_record(NULL::uuid)")
    with connection() as c:
        assert exact_text_edits.available(c)
        assert exact_marked_text_edits.available(c)
