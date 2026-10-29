"""Fresh isolated schema with actual API/Worker LOGINs; no HTTP acceptance implied."""

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_bid_package_repository import seed

from deploy.bootstrap_fresh import BASE_SQL, ROOT
from packages.domain.bid_package_repository import load_revision, save_revision

DSN = os.environ.get("FUSION_PACKAGE_ACL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires explicit fusion_package_acl database")


@pytest.fixture(scope="module")
def database():
    assert DSN
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as owner:
        assert (
            owner.execute("SELECT current_database() AS n").fetchone()["n"] == "fusion_package_acl"
        )
        assert owner.execute("SELECT to_regnamespace('design') AS n").fetchone()["n"] is None
        for name in BASE_SQL:
            owner.execute((ROOT / name).read_text(encoding="utf-8"))
        for login, group in (
            ("fusion_package_api", "tender_api"),
            ("fusion_package_worker", "tender_worker"),
        ):
            owner.execute(f"CREATE ROLE {login} LOGIN INHERIT")
            owner.execute(f"GRANT {group} TO {login}")
        yield owner
        for login in ("fusion_package_api", "fusion_package_worker"):
            owner.execute(f"DROP OWNED BY {login}")
            owner.execute(f"DROP ROLE {login}")
        owner.execute("DROP SCHEMA retrieval,design CASCADE")


def connect(login):
    c = psycopg.connect(make_conninfo(DSN, user=login), row_factory=dict_row)
    c.execute("SET search_path TO design,public")
    assert c.execute("SELECT current_user AS u").fetchone()["u"] == login
    return c


@pytest.fixture
def world(database, monkeypatch):
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "explicit-test-no-profile-read")
    with connect("fusion_package_api") as c:
        try:
            yield seed(c)
        finally:
            c.rollback()


def test_actual_api_login_can_save_and_load_frozen_revision(world):
    c, package = world["c"], world["package"]
    assert save_revision(c, package, expected_digest=None)["digest"] == package.manifest_digest
    assert load_revision(c, package.scope.bid_id, package.revision_id) == package
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="append_only"):
        with c.transaction():
            c.execute(
                "UPDATE bid_package_revisions SET manifest=manifest WHERE id=%s",
                (package.revision_id,),
            )


def test_worker_can_check_parse_freeze_but_cannot_write_packages(database):
    with connect("fusion_package_worker") as c:
        for table in (
            "bid_packages",
            "bid_package_revisions",
            "bid_package_heads",
            "bid_package_members",
            "bid_package_parts",
            "engineering_lots",
        ):
            assert not c.execute(
                "SELECT has_table_privilege(current_user,%s,'INSERT') AS p", ("design." + table,)
            ).fetchone()["p"]
        assert (
            c.execute("SELECT count(*) AS n FROM bid_package_parse_bindings").fetchone()["n"] == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with c.transaction():
                c.execute(
                    "INSERT INTO engineering_lots VALUES(gen_random_uuid(),gen_random_uuid(),'forbidden')"
                )


def test_worker_real_parse_trigger_distinguishes_unfrozen_and_frozen(database, monkeypatch):
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "explicit-test-no-profile-read")
    with connect("fusion_package_api") as api:
        world = seed(api)
        package = world["package"]
        api.commit()
        with connect("fusion_package_worker") as worker:
            run = package.members[0].parse.parse_run_id
            insertion = """INSERT INTO pages
                (bid_id,parse_id,physical_page,width,height,rotation,quality,gaps)
                VALUES(%s,%s,3,400,500,0,'usable','[]')"""
            parameters = (package.scope.bid_id, run)
            worker.execute(insertion, parameters)
            worker.rollback()
        save_revision(api, package, expected_digest=None)
        api.commit()
        with connect("fusion_package_worker") as worker:
            with pytest.raises(
                psycopg.errors.ObjectNotInPrerequisiteState, match="package_parse_is_frozen"
            ):
                worker.execute(insertion, parameters)


def test_new_helpers_have_no_public_execute_and_no_security_definer(database):
    rows = database.execute("""SELECT p.proname,p.prosecdef,
        EXISTS(SELECT FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='design' AND (p.proname LIKE 'package_%'
          OR p.proname IN ('frozen_package_parse_guard','identity_association_v2','identity_snapshot_v2'))""").fetchall()
    assert rows
    assert all(not row["public_execute"] and not row["prosecdef"] for row in rows)


def test_package_ddl_precedes_public_revoke_and_worker_grant_follows_it():
    assert BASE_SQL.index("packages/contracts/sql/domain.sql") < BASE_SQL.index(
        "packages/contracts/sql/bid-packages.sql"
    )
    assert BASE_SQL.index("packages/contracts/sql/bid-packages.sql") < BASE_SQL.index(
        "packages/identity/sql/stable-lot-identity.sql"
    )
    assert BASE_SQL.index("packages/identity/sql/stable-lot-identity.sql") < BASE_SQL.index(
        "packages/contracts/sql/roles.sql"
    )
    assert BASE_SQL.index("packages/contracts/sql/roles.sql") < BASE_SQL.index(
        "deploy/sql/bid-package-runtime-grants.sql"
    )


def test_api_lot_catalog_allows_registration_and_reading_without_mutation(database):
    with connect("fusion_package_api") as api:
        for privilege, allowed in (
            ("SELECT", True),
            ("INSERT", True),
            ("UPDATE", False),
            ("DELETE", False),
        ):
            row = api.execute(
                "SELECT has_table_privilege(current_user,'design.engineering_lots',%s) AS p",
                (privilege,),
            ).fetchone()
            assert row["p"] is allowed
