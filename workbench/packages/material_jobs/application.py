"""Framework-free request/recovery use cases with explicit transaction boundaries."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from packages.domain.errors import DomainError

Document = dict[str, Any]


@dataclass(frozen=True)
class Target:
    scope: tuple[str, ...]
    scope_id: str
    actor: str


class Transaction(Protocol):
    def prepare(
        self, target: Target, body: Document, condition: str | None, key: str | None
    ) -> str: ...
    def observe(
        self, target: Target, intent_id: str, reason: str = "NATIVE_ACCEPTANCE_PENDING"
    ) -> Document: ...
    def authorize(self, target: Target, intent_id: str) -> Document: ...
    def execution_state(self, target: Target, intent_id: str) -> Document: ...


class Transactions(Protocol):
    def __call__(self, readonly: bool = False) -> AbstractContextManager[Transaction]: ...


class NativeSubmit(Protocol):
    def __call__(self, command: Document) -> str: ...


@dataclass(frozen=True, repr=False)
class MaterialJobs:
    transactions: Transactions
    submit: NativeSubmit

    def request(
        self, target: Target, body: Document, condition: str | None, key: str | None
    ) -> Document:
        # Exiting the transaction must commit before a native operation can start.
        with self.transactions() as tx:
            identity = tx.prepare(target, body, condition, key)
        return self.resume(target, identity)

    def resume(self, target: Target, intent_id: str) -> Document:
        with self.transactions() as tx:
            value = tx.observe(target, intent_id)
            if value["job"] is not None:
                return value
            try:
                command = tx.authorize(target, intent_id)
            except DomainError as error:
                # A concurrent native commit may precede expiry/revocation.
                return tx.observe(target, intent_id, error.code)
        outcome = self.submit(command)
        with self.transactions() as tx:
            return tx.observe(target, intent_id, "NATIVE_" + outcome.upper())

    def read(self, target: Target, intent_id: str) -> Document:
        with self.transactions() as tx:
            return tx.observe(target, intent_id)

    def execution_state(self, target: Target, intent_id: str) -> Document:
        with self.transactions(readonly=True) as tx:
            return tx.execution_state(target, intent_id)
