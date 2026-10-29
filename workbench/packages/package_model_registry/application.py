"""Registry use cases with explicit transaction scope, no framework or DB imports."""

from typing import Protocol

from packages.package_model_registry import artifact


class Transaction(Protocol):
    def source(self, job_id, actor): ...
    def register(self, job_id, actor, document, key, reason): ...
    def read(self, model_id, actor): ...


class Registry:
    def __init__(self, transactions):
        self.transactions = transactions

    def preview(self, job_id, actor):
        with self.transactions() as tx:
            return artifact.build(tx.source(job_id, actor))

    def register(self, job_id, actor, key, reason, expected_digest):
        artifact.files.checksum(expected_digest)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4000:
            artifact.fail()
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or not key.strip():
            artifact.fail()
        with self.transactions() as tx:
            document = artifact.build(tx.source(job_id, actor))
            if artifact.digest(document) != expected_digest:
                artifact.fail()
            return tx.register(job_id, actor, document, key, reason)

    def read(self, model_id, actor):
        with self.transactions() as tx:
            receipt = tx.read(model_id, actor)
            artifact.validate(receipt["document"])
            if artifact.digest(receipt["document"]) != receipt["artifact_digest"]:
                artifact.fail()
            return receipt
