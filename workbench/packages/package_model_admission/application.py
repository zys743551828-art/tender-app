"""One transaction owns each protocol/report operation; no client-provided metrics."""

from typing import Protocol

from packages.package_model_admission import policy
from packages.package_model_registry import artifact


class Transaction(Protocol):
    def context(self, model, actor): ...
    def freeze(self, model, actor, document, key, reason): ...
    def read_protocol(self, model, actor): ...
    def report_source(self, model, job, actor): ...
    def register_report(self, model, job, actor, expected, key, reason): ...
    def read_report(self, model, actor): ...


class Admission:
    def __init__(self, transactions):
        self.transactions = transactions

    def context(self, model, actor):
        with self.transactions() as tx:
            value = tx.context(model, actor)
            artifact.validate(value["artifact"])
            return value

    def freeze(self, model, actor, document, key, reason):
        policy.validate(document)
        if document["binding"]["model_id"] != str(model):
            policy.fail()
        self._command(key, reason)
        with self.transactions() as tx:
            context = tx.context(model, actor)
            artifact.validate(context["artifact"])
            if document["binding"] != context["binding"]:
                policy.fail()
            return tx.freeze(model, actor, document, key, reason)

    def read_protocol(self, model, actor):
        with self.transactions() as tx:
            return tx.read_protocol(model, actor)

    def preview_report(self, model, job, actor):
        with self.transactions() as tx:
            packet = tx.report_source(model, job, actor)
            return {
                "packet": packet,
                "packet_digest": artifact.digest(packet),
                "assessment": policy.assess(packet),
            }

    def register_report(self, model, job, actor, expected, key, reason):
        artifact.files.checksum(expected)
        self._command(key, reason)
        with self.transactions() as tx:
            packet = tx.report_source(model, job, actor)
            if artifact.digest(packet) != expected:
                policy.fail()
            assessment = policy.assess(packet)
            record = tx.register_report(model, job, actor, expected, key, reason)
            return {"record": record, "assessment": assessment}

    def read_report(self, model, actor):
        with self.transactions() as tx:
            record = tx.read_report(model, actor)
            if artifact.digest(record["packet"]) != record["packet_digest"]:
                policy.fail()
            return {"record": record, "assessment": policy.assess(record["packet"])}

    @staticmethod
    def _command(key, reason):
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or not key.strip():
            policy.fail()
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4000:
            policy.fail()
