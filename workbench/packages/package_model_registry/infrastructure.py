"""Native packet/registry authority, with one owned connection per use case."""

from contextlib import contextmanager

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.runtime import DomainError


class NativeTransaction:
    def __init__(self, connection):
        self.c = connection

    def call(self, sql, params):
        if not self.c.execute(
            "SELECT to_regprocedure('package_model_registry.source(uuid,uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PACKAGE_MODEL_REGISTRY_UNAVAILABLE", "整包模型登记尚未配置", 503)
        try:
            return self.c.execute(sql, params).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {"42501", "55000", "22023", "23505"}:
                status = 403 if error.sqlstate == "42501" else 409
                raise DomainError(
                    "PACKAGE_MODEL_REGISTRY_REJECTED", "原生模型登记权威拒绝请求", status
                ) from None
            raise

    def source(self, job_id, actor):
        return self.call("SELECT package_model_registry.source(%s,%s) AS value", (job_id, actor))

    def register(self, job_id, actor, document, key, reason):
        return self.call(
            "SELECT package_model_registry.register(%s,%s,%s,%s,%s) AS value",
            (job_id, actor, Jsonb(document), key, reason),
        )

    def read(self, model_id, actor):
        return self.call("SELECT package_model_registry.read(%s,%s) AS value", (model_id, actor))


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as c:
            yield NativeTransaction(c)
