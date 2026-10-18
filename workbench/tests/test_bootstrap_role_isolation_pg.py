"""Explicit isolated PostgreSQL checks of the actual budget LOGIN's effective ACLs."""

import os

import psycopg
import pytest

from deploy import bootstrap_fresh as fresh

DSN = os.environ.get("FUSION_ROLE_ACL_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires an explicitly isolated ACL database")


@pytest.fixture(scope="module")
def acl_database():
    assert DSN is not None
    with psycopg.connect(DSN, autocommit=True) as admin:
        assert admin.execute("SELECT current_database()").fetchone() == ("fusion_role_acl",)
        assert admin.execute("SELECT to_regnamespace('design')").fetchone() == (None,)
        admin.execute(
            "CREATE SCHEMA design; CREATE SCHEMA retrieval; CREATE SCHEMA model_governance"
        )
        admin.execute("CREATE ROLE tender_assistant_budget_admin NOLOGIN")
        admin.execute("CREATE ROLE tender_api NOLOGIN")
        admin.execute("CREATE ROLE fusion_acl_intermediate NOLOGIN")
        admin.execute("CREATE ROLE fusion_acl_login LOGIN")
        admin.execute("GRANT tender_assistant_budget_admin TO fusion_acl_login")
        admin.execute("GRANT USAGE ON SCHEMA design TO tender_assistant_budget_admin")
        admin.execute("CREATE DOMAIN design.sha256 AS text")
        for name in (
            "assistant_price_versions",
            "assistant_budget_versions",
            "assistant_logical_intents",
            "assistant_budget_reservations",
            "assistant_budget_events",
        ):
            admin.execute(f"CREATE TABLE design.{name}(id integer)")
            admin.execute(f"GRANT SELECT ON design.{name} TO tender_assistant_budget_admin")
        admin.execute(
            "GRANT INSERT ON design.assistant_price_versions,design.assistant_budget_versions "
            "TO tender_assistant_budget_admin"
        )
        admin.execute("CREATE TABLE design.business_data(id integer)")
        admin.execute("CREATE SEQUENCE design.business_sequence")
        admin.execute(
            "CREATE FUNCTION design.assistant_reconcile_budget(uuid,text,bigint,text,design.sha256) "
            "RETURNS jsonb LANGUAGE sql AS 'SELECT null::jsonb'"
        )
        admin.execute(
            "CREATE FUNCTION design.business_command() RETURNS int LANGUAGE sql AS 'SELECT 1'"
        )
        admin.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA design FROM PUBLIC")
        admin.execute(
            "GRANT EXECUTE ON FUNCTION "
            "design.assistant_reconcile_budget(uuid,text,bigint,text,design.sha256) "
            "TO tender_assistant_budget_admin"
        )
        yield admin
        admin.execute("DROP SCHEMA model_governance,retrieval,design CASCADE")
        admin.execute(
            "DROP ROLE fusion_acl_login,fusion_acl_intermediate,tender_api,tender_assistant_budget_admin"
        )


def login_dsn():
    return psycopg.conninfo.make_conninfo(DSN, user="fusion_acl_login")


def test_real_nonowner_budget_login_has_only_the_allowed_effective_rights(acl_database):
    with psycopg.connect(login_dsn()) as login:
        fresh.verify_connection(
            login, database="fusion_role_acl", user="fusion_acl_login", restricted=True
        )
        fresh.verify_budget_login_isolation(login)


FAULTS = [
    (
        "upstream_api",
        "GRANT tender_api TO tender_assistant_budget_admin",
        "REVOKE tender_api FROM tender_assistant_budget_admin",
        "GROUP_HAS_UPSTREAM_MEMBERSHIP",
    ),
    (
        "transitive_noinherit_set_path",
        "GRANT tender_api TO fusion_acl_intermediate; "
        "GRANT fusion_acl_intermediate TO tender_assistant_budget_admin WITH INHERIT FALSE",
        "REVOKE fusion_acl_intermediate FROM tender_assistant_budget_admin; "
        "REVOKE tender_api FROM fusion_acl_intermediate",
        "GROUP_HAS_UPSTREAM_MEMBERSHIP",
    ),
    (
        "additional_login_group",
        "GRANT tender_api TO fusion_acl_login",
        "REVOKE tender_api FROM fusion_acl_login",
        "LOGIN_MEMBERSHIP_NOT_EXACT",
    ),
    (
        "admin_option",
        "GRANT tender_assistant_budget_admin TO fusion_acl_login WITH ADMIN OPTION",
        "REVOKE ADMIN OPTION FOR tender_assistant_budget_admin FROM fusion_acl_login",
        "LOGIN_MEMBERSHIP_NOT_EXACT",
    ),
    (
        "public_table_select",
        "GRANT SELECT ON design.business_data TO PUBLIC",
        "REVOKE SELECT ON design.business_data FROM PUBLIC",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "direct_column_select",
        "GRANT SELECT(id) ON design.business_data TO fusion_acl_login",
        "REVOKE SELECT(id) ON design.business_data FROM fusion_acl_login",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "business_execute",
        "GRANT EXECUTE ON FUNCTION design.business_command() TO fusion_acl_login",
        "REVOKE EXECUTE ON FUNCTION design.business_command() FROM fusion_acl_login",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "schema_create",
        "GRANT CREATE ON SCHEMA design TO fusion_acl_login",
        "REVOKE CREATE ON SCHEMA design FROM fusion_acl_login",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "sequence_usage",
        "GRANT USAGE ON SEQUENCE design.business_sequence TO fusion_acl_login",
        "REVOKE USAGE ON SEQUENCE design.business_sequence FROM fusion_acl_login",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "allowed_function_owner",
        "ALTER FUNCTION design.assistant_reconcile_budget(uuid,text,bigint,text,design.sha256) OWNER TO fusion_acl_login",
        "ALTER FUNCTION design.assistant_reconcile_budget(uuid,text,bigint,text,design.sha256) OWNER TO postgres",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "direct_business_write",
        "GRANT UPDATE ON design.business_data TO fusion_acl_login",
        "REVOKE UPDATE ON design.business_data FROM fusion_acl_login",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "pg17_maintain",
        "GRANT MAINTAIN ON design.business_data TO fusion_acl_login",
        "REVOKE MAINTAIN ON design.business_data FROM fusion_acl_login",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
    (
        "inherited_allowed_function_owner",
        "ALTER FUNCTION design.assistant_reconcile_budget(uuid,text,bigint,text,design.sha256) OWNER TO tender_assistant_budget_admin",
        "ALTER FUNCTION design.assistant_reconcile_budget(uuid,text,bigint,text,design.sha256) OWNER TO postgres",
        "FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES",
    ),
]


@pytest.mark.parametrize("name,grant,revoke,error", FAULTS, ids=[row[0] for row in FAULTS])
def test_real_effective_privilege_pollution_is_rejected(acl_database, name, grant, revoke, error):
    acl_database.execute(grant)
    try:
        with psycopg.connect(login_dsn()) as login:
            with pytest.raises(fresh.BootstrapError, match=error):
                fresh.verify_budget_login_isolation(login)
    finally:
        acl_database.execute(revoke)
