"""Registration/read orchestration; object I/O never holds a SQL transaction."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

Document = dict[str, Any]


@dataclass(frozen=True, repr=False)
class Register:
    actor: str
    training_job_id: UUID
    reason: str
    body: Document
    condition: str | None
    key: str | None


@dataclass(frozen=True, repr=False)
class Outcome:
    result: Document
    replayed: bool = False


@dataclass(frozen=True, repr=False)
class Plan:
    document: Document
    tag: str
    replay: Outcome | None = None


class Transaction(Protocol):
    def prepare(self, request: Register) -> Plan: ...
    def finish(self, request: Register, staged: Document, original_tag: str) -> Outcome: ...
    def stored(self, model_id: UUID) -> Document: ...
    def view(self, model_id: UUID) -> tuple[Document, str]: ...


class Transactions(Protocol):
    def __call__(self) -> AbstractContextManager[Transaction]: ...


class Objects(Protocol):
    def stage(self, document: Document) -> Document: ...
    def verify(self, stored: Document) -> None: ...


@dataclass(frozen=True, repr=False)
class ModelRegistration:
    transactions: Transactions
    objects: Objects

    def register(self, request: Register) -> Outcome:
        with self.transactions() as tx:
            plan = tx.prepare(request)
        if plan.replay is not None:
            return plan.replay
        staged = self.objects.stage(plan.document)
        with self.transactions() as tx:
            return tx.finish(request, staged, plan.tag)

    def read(self, model_id: UUID) -> tuple[Document, str]:
        with self.transactions() as tx:
            stored = tx.stored(model_id)
        self.objects.verify(stored)
        with self.transactions() as tx:
            return tx.view(model_id)
