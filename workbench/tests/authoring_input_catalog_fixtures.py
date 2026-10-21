"""Disposable catalog DB, existing B1 producers, and no duplicated application routes."""
# ruff: noqa: F401

import os
import secrets

import psycopg
import pytest
from authoring_package_input_fixtures import DDL, exact, save, world
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_stable_lot_identity import uid

ADMIN_DSN = os.environ.get("FUSION_AUTHORING_INPUT_ADMIN_DSN")


@pytest.fixture(scope="module")
def database():
    from apps.api.authoring_input_catalog_routes import router
    from apps.api.main import app
    from deploy.bootstrap_fresh import BASE_SQL, ROOT
    from packages.authoring.package_input_repository import capabilities
    from packages.contracts.authoring_input_catalog_api import ROOTS

    assert DDL not in BASE_SQL
    old_routes = list(app.router.routes)
    mounted = {getattr(route, "path", None) for route in app.router.routes}
    assert not (set(ROOTS) & mounted) or set(ROOTS) <= mounted
    if not set(ROOTS) <= mounted:
        app.include_router(router)
    app.openapi_schema = None
    dbname = "fusion_authoring_package_inputs"
    roles = {"api": dbname + "_api", "worker": dbname + "_worker"}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_ENV_FILE", "explicit-authoring-input-no-business-profile")
        patch.setenv("APP_ORIGIN", "http://identity-v2.test")
        patch.setenv("SESSION_SECRET", uid())
        patch.setenv("CSRF_SECRET", uid())
        with psycopg.connect(ADMIN_DSN, autocommit=True, row_factory=dict_row) as admin:
            assert admin.info.dbname == "postgres"
            assert not admin.execute(
                "SELECT FROM pg_database WHERE datname=%s", (dbname,)
            ).fetchone()
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(dbname))
            )
            try:
                owner_dsn = make_conninfo(ADMIN_DSN, dbname=dbname)
                with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
                    for name in BASE_SQL:
                        owner.execute((ROOT / name).read_text())
                    owner.execute(
                        (ROOT / "deploy/sql/bid-package-requirement-runtime-grants.sql").read_text()
                    )
                    connections = {}
                    for kind, name in roles.items():
                        password = secrets.token_urlsafe(36)
                        admin.execute(
                            sql.SQL(
                                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                            ).format(sql.Identifier(name), sql.Literal(password))
                        )
                        admin.execute(
                            sql.SQL("GRANT {} TO {}").format(
                                sql.Identifier("tender_" + kind), sql.Identifier(name)
                            )
                        )
                        connections[kind + "_dsn"] = make_conninfo(
                            owner_dsn, user=name, password=password
                        )
                    patch.setenv("API_DATABASE_DSN", connections["api_dsn"])
                    patch.setenv("WORKER_DATABASE_DSN", connections["worker_dsn"])
                    with psycopg.connect(
                        connections["api_dsn"], row_factory=dict_row
                    ) as api_connection:
                        before = capabilities(api_connection)
                        assert not before["capture_available"]
                    owner.execute((ROOT / DDL).read_text())
                    yield {"owner": owner, "base_capabilities": before, **connections}
            finally:
                app.router.routes[:] = old_routes
                app.openapi_schema = None
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(dbname))
                )
                for name in roles.values():
                    admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))
