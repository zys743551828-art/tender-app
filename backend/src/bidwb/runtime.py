"""进程级依赖的装配：配置、数据库引擎、对象存储。API 与各类 worker 共用。"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine

from bidwb import db
from bidwb.config import Settings
from bidwb.services.auth import LoginRateLimiter
from bidwb.storage import ObjectStore, S3ObjectStore


@dataclass
class Container:
    settings: Settings
    engine: Engine
    store: ObjectStore
    login_limiter: LoginRateLimiter = field(init=False)

    def __post_init__(self) -> None:
        self.login_limiter = LoginRateLimiter(self.settings.login_rate_limit_per_minute)

    def close(self) -> None:
        self.engine.dispose()


def build_api_container(settings: Settings) -> Container:
    engine = db.make_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        pool_timeout=settings.db_pool_timeout_seconds,
        application_name="bidwb-api",
    )
    return Container(settings, engine, S3ObjectStore(settings))


def build_worker_container(settings: Settings, name: str) -> Container:
    engine = db.make_engine(settings.worker_dsn(), pool_size=3, pool_timeout=settings.db_pool_timeout_seconds, application_name=name)
    return Container(settings, engine, S3ObjectStore(settings))
