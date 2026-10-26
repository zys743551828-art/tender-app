"""Existing API role, no new credentials or roles; private native evidence reads."""

from contextlib import contextmanager

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.errors import DomainError


class Transaction:
    def __init__(self, connection):
        self.c = connection

    def call(self, function, args):
        # Function names are constants in methods below, never HTTP input.
        if not self.c.execute(
            "SELECT to_regprocedure('package_model_observation.business_source(uuid,uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("BUSINESS_SHADOW_UNAVAILABLE", "业务镜像未安装", 503)
        try:
            marks = ",".join(["%s"] * len(args))
            return self.c.execute(f"SELECT {function}({marks}) AS value", args).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {"42501", "55000", "22023", "23505", "40001", "P0002"}:
                raise DomainError(
                    "BUSINESS_SHADOW_REJECTED",
                    "业务镜像权威拒绝请求",
                    403 if error.sqlstate == "42501" else 409,
                ) from None
            raise

    def begin_capture(self, actor, job, profile, method, kind, pid):
        return self.call(
            "package_model_observation.begin_capture", (actor, job, profile, method, kind, pid)
        )

    def finish_capture(self, actor, capture, method):
        return self.call("package_model_observation.finish_capture", (actor, capture, method))

    def freeze(self, actor, model, expected, key, contract):
        return self.call(
            "package_model_admission.bind_business_evidence",
            (actor, model, expected, key, Jsonb(contract)),
        )

    def replay(self, actor, body):
        return self.call("package_model_route.business_replay", (actor, Jsonb(body)))

    def prepare(self, actor, body):
        return self.call("package_model_route.business_prepare", (actor, Jsonb(body)))

    def commit(self, actor, body, pinned, result):
        return self.call(
            "package_model_route.business_commit", (actor, Jsonb(body), pinned, Jsonb(result))
        )


class NativeTransactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self):
        with self.connections() as connection:
            yield Transaction(connection)
