"""Fresh unified authority snapshot, expensive projection outside transactions."""

from packages.domain.review_identity import digest
from packages.package_model_registry.artifact import fail
from packages.package_prediction_reports.application import Reports
from packages.package_unified_reports.projection import compose, document, method_digest


class UnifiedReports:
    def __init__(self, transactions, projector):
        self.transactions, self.projector = transactions, projector

    def snapshot(self, tx, actor, bid, scope, command, run, simulation):
        receipt, packet = Reports.snapshot(tx, actor, bid, scope, command)
        sources = tx.components(bid, packet, run, simulation)
        return {
            "receipt": receipt,
            "packet": packet,
            "sources": sources,
            "method_digest": method_digest(),
        }

    def render(self, actor, bid, scope, command, run, simulation=None, format="json"):
        if format not in {"json", "docx"}:
            fail()
        with self.transactions() as tx:
            snapshot = self.snapshot(tx, actor, bid, scope, command, run, simulation)
        identity = digest(snapshot)
        prediction = self.projector(snapshot["packet"], snapshot["receipt"])
        result = compose(snapshot, prediction, identity)
        if digest(snapshot) != identity:
            fail()
        output = document(result) if format == "docx" else result
        with self.transactions() as tx:
            after = self.snapshot(tx, actor, bid, scope, command, run, simulation)
            if digest(after) != identity:
                fail()
        return output
