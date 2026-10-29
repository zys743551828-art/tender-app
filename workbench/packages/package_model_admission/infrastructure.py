"""Database owns immutable bindings and exposure timing; no parallel evidence store."""

from contextlib import contextmanager

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.runtime import DomainError


class NativeTransaction:
    def __init__(self, connection):
        self.c = connection

    def call(self, sql, params):
        if not self.c.execute(
            "SELECT to_regprocedure('package_model_admission.context(uuid,uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PACKAGE_ADMISSION_UNAVAILABLE", "整包业务门槛与报告登记未配置", 503)
        try:
            return self.c.execute(sql, params).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {"42501", "55000", "22023", "23505", "22P02"}:
                raise DomainError(
                    "PACKAGE_ADMISSION_REJECTED",
                    "原生准入证据校验拒绝请求",
                    403 if error.sqlstate == "42501" else 409,
                ) from None
            raise

    def context(self, model, actor):
        return self.call("SELECT package_model_admission.context(%s,%s) AS value", (model, actor))

    def freeze(self, model, actor, document, key, reason):
        return self.call(
            "SELECT package_model_admission.freeze_protocol(%s,%s,%s,%s,%s) AS value",
            (model, actor, Jsonb(document), key, reason),
        )

    def read_protocol(self, model, actor):
        return self.call(
            "SELECT package_model_admission.read_protocol(%s,%s) AS value", (model, actor)
        )

    def report_source(self, model, job, actor):
        return self.call(
            "SELECT package_model_admission.report_source(%s,%s,%s) AS value", (model, job, actor)
        )

    def register_report(self, model, job, actor, expected, key, reason):
        return self.call(
            "SELECT package_model_admission.register_report(%s,%s,%s,%s,%s,%s) AS value",
            (model, job, actor, expected, key, reason),
        )

    def read_report(self, model, actor):
        return self.call(
            "SELECT package_model_admission.read_report(%s,%s) AS value", (model, actor)
        )


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as c:
            yield NativeTransaction(c)
