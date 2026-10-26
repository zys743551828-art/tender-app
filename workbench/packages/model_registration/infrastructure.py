"""Delegate to existing immutable registry, Command and object-store authority."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from packages.domain.runtime import Command
from packages.model_governance import registry
from packages.model_governance.repository import match
from packages.model_registration.application import Document, Outcome, Plan, Register, Transaction


class SqlTransaction:
    def __init__(self, connection: Any):
        self._connection = connection

    def _command(self, request: Register):
        return Command(
            self._connection,
            request.actor,
            "register-score-model",
            request.training_job_id,
            request.key,
            request.body,
            request.condition,
        )

    def prepare(self, request: Register) -> Plan:
        preview, tag = registry.preview(self._connection, request.training_job_id)
        old = self._connection.execute(
            "SELECT response FROM commands WHERE actor_id=%s AND command_kind='register-score-model' AND target_id=%s AND idempotency_key=%s",
            (request.actor, request.training_job_id, request.key),
        ).fetchone()
        if old and old["response"]:
            return Plan(preview["document"], tag, Outcome(self._command(request).replay, True))
        match(request.condition, tag)
        return Plan(preview["document"], tag)

    def finish(self, request: Register, staged: Document, original_tag: str) -> Outcome:
        latest, latest_tag = registry.preview(self._connection, request.training_job_id)
        command = self._command(request)
        if command.replay:
            return Outcome(command.replay, True)
        result, result_tag = registry.publish(
            self._connection,
            actor=request.actor,
            training_job_id=request.training_job_id,
            document=latest["document"],
            staged=staged,
            condition=request.condition,
            reason=request.reason,
            command=command.id,
        )
        match(latest_tag, original_tag)
        return Outcome(command.finish(result, 201, {"ETag": result_tag}))

    def stored(self, model_id: UUID) -> Document:
        return registry.blob(self._connection, model_id)

    def view(self, model_id: UUID) -> tuple[Document, str]:
        return registry.view(self._connection, model_id)


class SqlTransactions:
    def __init__(self, connect: Callable):
        self._connect = connect

    @contextmanager
    def __call__(self) -> Iterator[Transaction]:
        with self._connect() as connection:
            yield SqlTransaction(connection)


class RegistryObjects:
    def stage(self, document: Document) -> Document:
        return registry.stage(document)

    def verify(self, stored: Document) -> None:
        registry.read(stored)
