"""One transaction for source checks and issuance; replay does not renew authority."""

from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_model_certification import policy


class Certificates:
    def __init__(self, transactions):
        self.transactions = transactions

    def preview(self, actor, model, body):
        policy.request(body)
        with self.transactions() as tx:
            packet = tx.source(actor, model, body)
            binding = policy.assess(packet, model, body, tx.now())
            return {
                "source_digest": digest(packet),
                "binding": binding,
                "eligible_for_requested_lifetime": True,
                "certification_issued": False,
            }

    def issue(self, actor, model, body, key, expected):
        policy.request(body)
        policy.artifact.files.command(key)
        policy.artifact.files.checksum(expected)
        with self.transactions() as tx:
            previous = tx.replay(actor, model, body, key, expected, policy.method_digest())
            if previous is not None:
                return self._view(previous, tx.now())
            packet = tx.source(actor, model, body)
            policy.assess(packet, model, body, tx.now())
            if digest(packet) != expected:
                policy.admission.fail()
            return self._view(
                tx.issue(actor, model, body, key, expected, policy.method_digest()), tx.now()
            )

    def read(self, actor, certificate):
        with self.transactions() as tx:
            return self._view(tx.read(actor, certificate, policy.method_digest()), tx.now())

    def revoke(self, actor, certificate, key, reason):
        policy.artifact.files.command(key)
        policy.reason(reason)
        with self.transactions() as tx:
            return self._view(
                tx.revoke(actor, certificate, key, reason, policy.method_digest()), tx.now()
            )

    @staticmethod
    def _view(record, now):
        certificate, state = record["certificate"], record["state"]
        if state == "active":
            try:
                if (
                    certificate["method_digest"] != policy.method_digest()
                    or digest(record["source"]) != certificate["source_digest"]
                ):
                    policy.admission.fail()
                policy.assess(
                    record["source"], certificate["model_id"], certificate["request"], now
                )
            except (GovernanceError, KeyError, TypeError, ValueError):
                state = "stale"
        return {
            "schema": policy.VERSION,
            "certificate": certificate,
            "state": state,
            "eligible": state == "active",
            "current_authority_checked": True,
            "prediction_issued": False,
        }
