"""Native route authority, one owned connection per short transaction."""

from contextlib import contextmanager

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.errors import DomainError


class NativeTransaction:
    def __init__(self, connection):
        self.c = connection

    def call(self, sql, params):
        if not self.c.execute(
            "SELECT to_regprocedure('package_model_route.prepare(uuid,jsonb)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PACKAGE_INTERNAL_ROUTE_UNAVAILABLE", "内部路由尚未配置", 503)
        try:
            return self.c.execute(sql, params).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {"42501", "55000", "22023", "23505", "40001", "P0002"}:
                raise DomainError(
                    "PACKAGE_INTERNAL_ROUTE_REJECTED",
                    "内部路由权威拒绝请求",
                    403 if error.sqlstate == "42501" else 409,
                ) from None
            raise

    def replay(self, actor, request):
        return self.call(
            "SELECT package_model_route.replay(%s,%s) AS value", (actor, Jsonb(request))
        )

    def prepare(self, actor, request):
        return self.call(
            "SELECT package_model_route.prepare(%s,%s) AS value", (actor, Jsonb(request))
        )

    def commit(self, actor, request, packet_digest, result):
        return self.call(
            "SELECT package_model_route.commit_action(%s,%s,%s,%s) AS value",
            (actor, Jsonb(request), packet_digest, Jsonb(result)),
        )


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as connection:
            yield NativeTransaction(connection)
