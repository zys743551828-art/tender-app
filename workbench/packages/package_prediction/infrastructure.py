"""Native adapter using existing roles and private CAS injection."""

from contextlib import contextmanager

from psycopg import Error, sql
from psycopg.types.json import Jsonb

from packages.domain.errors import DomainError


class NativeTransaction:
    def __init__(self, connection):
        self.c = connection

    def now(self):
        return self.c.execute("SELECT clock_timestamp()::text AS value").fetchone()["value"]

    def call(self, name, args):
        if not self.c.execute(
            "SELECT to_regprocedure('package_prediction.read(uuid,uuid,uuid,uuid,text,text)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PACKAGE_PREDICTION_UNAVAILABLE", "正式预测尚未配置", 503)
        try:
            return self.c.execute(
                sql.SQL("SELECT package_prediction.{}({}) AS value").format(
                    sql.Identifier(name), sql.SQL(",").join(sql.Placeholder() for _ in args)
                ),
                args,
            ).fetchone()["value"]
        except Error as e:
            if e.sqlstate in {"42501", "55000", "22023", "23505", "40001", "22P02"}:
                raise DomainError(
                    "PACKAGE_PREDICTION_REJECTED",
                    "预测资格、输入或版本已失效",
                    403 if e.sqlstate == "42501" else 409,
                ) from None
            raise

    def prepare(self, actor, bid, scope, certificate, method, cert_method):
        return self.call("prepare", (actor, bid, scope, certificate, method, cert_method))

    def read(self, actor, bid, scope, command, method, cert_method):
        return self.call("read", (actor, bid, scope, command, method, cert_method))

    def commit(self, actor, bid, scope, certificate, command, pinned, result, method, cert_method):
        return self.call(
            "commit",
            (actor, bid, scope, certificate, command, pinned, Jsonb(result), method, cert_method),
        )


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as connection:
            yield NativeTransaction(connection)
