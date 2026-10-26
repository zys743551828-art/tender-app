"""Short native transactions over existing evidence authority."""

from contextlib import contextmanager

from psycopg import Error, sql
from psycopg.types.json import Jsonb

from packages.domain.runtime import DomainError


class NativeTransaction:
    def __init__(self, connection):
        self.c = connection

    def now(self):
        return self.c.execute("SELECT clock_timestamp()::text AS value").fetchone()["value"]

    def call(self, function, params):
        if not self.c.execute(
            "SELECT to_regprocedure('package_model_admission.read_certificate(uuid,uuid,text)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PACKAGE_CERTIFICATION_UNAVAILABLE", "认证生命周期未配置", 503)
        try:
            return self.c.execute(
                sql.SQL("SELECT package_model_admission.{}({}) AS value").format(
                    sql.Identifier(function), sql.SQL(",").join(sql.Placeholder() for _ in params)
                ),
                params,
            ).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {"42501", "55000", "22023", "23505", "22P02", "40001"}:
                raise DomainError(
                    "PACKAGE_CERTIFICATION_REJECTED",
                    "认证权威证据或请求冲突",
                    403 if error.sqlstate == "42501" else 409,
                ) from None
            raise

    def source(self, actor, model, body):
        return self.call(
            "certification_source",
            (actor, model, body["shadow_event_id"], body["rollback_event_id"]),
        )

    def replay(self, actor, model, body, key, expected, method):
        return self.call("certificate_replay", (actor, model, Jsonb(body), key, expected, method))

    def issue(self, actor, model, body, key, expected, method):
        return self.call("issue_certificate", (actor, model, Jsonb(body), key, expected, method))

    def read(self, actor, certificate, method):
        return self.call("read_certificate", (actor, certificate, method))

    def revoke(self, actor, certificate, key, reason, method):
        return self.call("revoke_certificate", (actor, certificate, key, reason, method))


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as connection:
            yield NativeTransaction(connection)
