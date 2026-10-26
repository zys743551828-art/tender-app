"""Adapters to existing transaction/SQL authority; no new persistence or grants."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from packages.material_jobs.application import Document, Target, Transaction
from packages.model_governance import material_execution_status as status
from packages.model_governance import material_qualification_guard as guard
from packages.model_governance import material_qualified_jobs as qualified


class SqlTransaction:
    def __init__(self, connection: Any):
        self._connection = connection
        self._intents: dict[tuple[Target, str], Document] = {}

    def _intent(self, target: Target, identity: str) -> Document:
        key = target, identity
        if key not in self._intents:
            self._intents[key] = qualified.intent(
                self._connection, target.scope, target.scope_id, target.actor, identity
            )
        return self._intents[key]

    def prepare(
        self, target: Target, body: Document, condition: str | None, key: str | None
    ) -> str:
        return qualified.prepare(
            self._connection, target.scope, target.scope_id, target.actor, body, condition, key
        )

    def observe(
        self, target: Target, intent_id: str, reason: str = "NATIVE_ACCEPTANCE_PENDING"
    ) -> Document:
        return qualified.observe(
            self._connection, self._intent(target, intent_id), pending_reason=reason
        )

    def authorize(self, target: Target, intent_id: str) -> Document:
        row = self._intent(target, intent_id)
        guard.audit(self._connection)
        if row["document"].get("guard_digest") != guard.method_digest():
            qualified.policy.fail("GUARD_CHANGED", "原申请的资格守卫版本已变化", 409)
        qualified.current(self._connection, target.scope_id, row["document"]["request"])
        return row["document"]["command"]

    def execution_state(self, target: Target, intent_id: str) -> Document:
        return status.observe(self._connection, self._intent(target, intent_id))


class SqlTransactions:
    """One fresh context and intent cache per use; never a shared connection/session."""

    def __init__(self, connect: Callable):
        self._connect = connect

    @contextmanager
    def __call__(self, readonly: bool = False) -> Iterator[Transaction]:
        with self._connect() as connection:
            if readonly:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            yield SqlTransaction(connection)
