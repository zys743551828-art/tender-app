"""测试夹具：每个测试会话建一个独立的 PostgreSQL 库，跑完整 Alembic 迁移，再按测试清空数据。

需要环境变量 ``BIDWB_TEST_ADMIN_DSN`` 指向有建库权限的实例（默认 ``postgresql+psycopg://postgres@127.0.0.1:5432/postgres``）。
连不上时集成测试整体跳过，而不是失败，纯单元测试仍会运行。
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from bidwb import db
from bidwb.storage import MemoryObjectStore

BACKEND = Path(__file__).resolve().parent.parent
ADMIN_DSN = os.environ.get("BIDWB_TEST_ADMIN_DSN", "postgresql+psycopg://postgres@127.0.0.1:5432/postgres")
DATA_TABLES_SQL = """SELECT string_agg(format('%I', tablename), ',') FROM pg_tables
                     WHERE schemaname='public' AND tablename <> 'alembic_version'"""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _admin_engine_or_none() is not None:
        return
    skip = pytest.mark.skip(reason="没有可用的 PostgreSQL（设置 BIDWB_TEST_ADMIN_DSN）")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _admin_engine_or_none() -> Engine | None:
    try:
        engine = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    admin = _admin_engine_or_none()
    if admin is None:
        pytest.skip("没有可用的 PostgreSQL")
    name = f"bidwb_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_DSN).set(database=name).render_as_string(hide_password=False)
    env = {**os.environ, "BIDWB_MIGRATION_DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = db.make_engine(database_url, pool_size=5, application_name="bidwb-test")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> Iterator[None]:
    """集成测试之间互不影响：每个测试前清空所有业务表。

    追加保存表带有禁止 TRUNCATE 的触发器，因此以会话级 ``session_replication_role=replica`` 绕过触发器清表，
    这只发生在测试库里。
    """
    if "engine" not in request.fixturenames:
        yield
        return
    eng: Engine = request.getfixturevalue("engine")
    with eng.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        tables = conn.execute(text(DATA_TABLES_SQL)).scalar()
        if tables:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def store() -> MemoryObjectStore:
    return MemoryObjectStore()


# ------------------------------------------------------------------ API 夹具
from fastapi.testclient import TestClient  # noqa: E402

from bidwb.api.app import create_app  # noqa: E402
from bidwb.config import Settings  # noqa: E402
from bidwb.runtime import Container  # noqa: E402
from bidwb.services import auth as auth_service  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test", cookie_secure=False, session_cookie_name="sid", login_rate_limit_per_minute=1000, auto_analysis=False
    )


@pytest.fixture
def container(settings: Settings, engine: Engine, store: MemoryObjectStore) -> Container:
    return Container(settings, engine, store)


@pytest.fixture
def make_member(engine: Engine):  # type: ignore[no-untyped-def]
    def _make(login: str, name: str | None = None) -> str:
        with db.transaction(engine) as conn:
            return auth_service.create_local_member(conn, login=login, display_name=name or login, password=PASSWORD)

    return _make


class Api:
    """带会话与 CSRF 的测试客户端：像浏览器一样自动带 cookie、令牌和幂等键。"""

    def __init__(self, app_client: TestClient) -> None:
        self.http = app_client
        self.csrf = ""
        self._n = 0

    def login(self, login: str, password: str = PASSWORD) -> Api:
        r = self.http.post("/api/v1/auth/login", json={"username": login, "password": password})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        return self

    def _headers(self, key: str | None, extra: dict[str, str] | None) -> dict[str, str]:
        self._n += 1
        return {"X-CSRF-Token": self.csrf, "Idempotency-Key": key or f"test-key-{uuid.uuid4().hex}", **(extra or {})}

    def get(self, path: str, **kw):  # type: ignore[no-untyped-def]
        return self.http.get("/api/v1" + path, **kw)

    def post(self, path: str, json: object = None, *, key: str | None = None, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
        return self.http.post("/api/v1" + path, json=json if json is not None else {}, headers=self._headers(key, headers))

    def patch(self, path: str, json: object, *, key: str | None = None, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
        return self.http.patch("/api/v1" + path, json=json, headers=self._headers(key, headers))

    def put(self, path: str, json: object, *, key: str | None = None, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
        return self.http.put("/api/v1" + path, json=json, headers=self._headers(key, headers))


@pytest.fixture
def api_factory(settings: Settings, container: Container):  # type: ignore[no-untyped-def]
    app = create_app(settings, container)

    def _new() -> Api:
        return Api(TestClient(app, base_url="http://testserver"))

    return _new


@pytest.fixture(scope="session")
def worker_engine(database_url: str) -> Iterator[Engine]:
    """以受限角色 ``app_worker`` 登录的引擎：证明 worker 路径只用到被授予的权限。"""
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bidwb_test_worker') "
                "THEN CREATE ROLE bidwb_test_worker LOGIN IN ROLE app_worker; END IF; END $$"
            )
        )
    admin.dispose()
    url = make_url(database_url).set(username="bidwb_test_worker").render_as_string(hide_password=False)
    eng = db.make_engine(url, pool_size=5, application_name="bidwb-test-worker")
    yield eng
    eng.dispose()


@pytest.fixture
def worker_container(settings: Settings, worker_engine: Engine, store: MemoryObjectStore) -> Container:
    return Container(settings, worker_engine, store)
