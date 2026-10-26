"""No cached grants: recheck the exact receipt, certificate and display policy."""

from packages.domain.review_identity import digest
from packages.package_model_certification.policy import method_digest as certificate_method
from packages.package_model_registry import artifact
from packages.package_prediction.application import method_digest as prediction_method
from packages.package_prediction_reports import projection


class Reports:
    def __init__(self, transactions, projector):
        self.transactions, self.projector = transactions, projector

    @staticmethod
    def snapshot(tx, actor, bid, scope, command):
        receipt = tx.read(actor, bid, scope, command, prediction_method(), certificate_method())
        if receipt is None or receipt["state"] not in {"valid", "hidden"}:
            artifact.fail()
        packet = tx.prepare(
            actor, bid, scope, receipt["certificate_id"], prediction_method(), certificate_method()
        )
        return receipt, packet

    def render(self, actor, bid, scope, command, format="json"):
        if format not in {"json", "docx"}:
            artifact.fail()
        with self.transactions() as tx:
            receipt, packet = self.snapshot(tx, actor, bid, scope, command)
        pinned = digest({"receipt": receipt, "packet": packet})
        result = self.projector(packet, receipt)
        if digest({"receipt": receipt, "packet": packet}) != pinned:
            artifact.fail()
        output = projection.document(result) if format == "docx" else result
        with self.transactions() as tx:
            after_receipt, after_packet = self.snapshot(tx, actor, bid, scope, command)
            if digest({"receipt": after_receipt, "packet": after_packet}) != pinned:
                artifact.fail()
        return output
