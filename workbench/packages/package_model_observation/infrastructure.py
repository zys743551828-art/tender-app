"""Owned native API-role transactions; no fallback authority or configuration."""

from contextlib import contextmanager

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.errors import DomainError


class NativeTransaction:
    def __init__(self, connection):
        self.c = connection

    def call(self, sql, params):
        if not self.c.execute(
            "SELECT to_regprocedure('package_model_observation.source(uuid,uuid,uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PACKAGE_OBSERVATION_UNAVAILABLE", "内部观察尚未配置", 503)
        try:
            return self.c.execute(sql, params).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {"42501", "55000", "22023", "23505", "40001", "P0002"}:
                raise DomainError(
                    "PACKAGE_OBSERVATION_REJECTED",
                    "内部观察权威拒绝请求",
                    403 if error.sqlstate == "42501" else 409,
                ) from None
            raise

    def replay(self, actor, request):
        return self.call(
            "SELECT package_model_observation.replay(%s,%s) AS value", (actor, Jsonb(request))
        )

    def source(self, actor, request):
        return self.call(
            "SELECT package_model_observation.source(%s,%s,%s) AS value",
            (actor, request["model_id"], request["admission_id"]),
        )

    def record(self, actor, request, source_digest, result):
        return self.call(
            "SELECT package_model_observation.record(%s,%s,%s,%s) AS value",
            (actor, Jsonb(request), source_digest, Jsonb(result)),
        )


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as connection:
            yield NativeTransaction(connection)
