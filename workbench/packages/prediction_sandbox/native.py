"""Short transactions on existing API role; isolated schema never grants Worker rights."""

from contextlib import contextmanager

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.errors import DomainError
from packages.lifecycle.service import assert_work_writable, lock
from packages.package_prediction_tasks.native import Transaction


class SandboxTransaction(Transaction):
    def writable(self, bid):
        assert_work_writable(self.c, bid)

    def sandbox(self, body, action, payload):
        try:
            return self.c.execute(
                "SELECT prediction_sandbox.operate(%s,%s,%s,%s,%s) AS value",
                (body["actor"], body["bid"], body.get("certificate"), action, Jsonb(payload)),
            ).fetchone()["value"]
        except Error as error:
            if error.sqlstate in {
                "42501",
                "55000",
                "22023",
                "23505",
                "22P02",
                "42P01",
                "42883",
                "3F000",
                "22007",
                "22008",
                "23502",
                "23514",
                "22003",
            }:
                raise DomainError(
                    "PREDICTION_SANDBOX_REJECTED", "仅测试资格、材料或运行环境已失效", 409
                ) from None
            raise


class Transactions:
    def __init__(self, connections):
        self.connections = connections

    @contextmanager
    def __call__(self, body):
        with self.connections() as c:
            lock(c, body["bid"])
            c.execute("SELECT pg_advisory_xact_lock(91143,1)")
            yield SandboxTransaction(c)
