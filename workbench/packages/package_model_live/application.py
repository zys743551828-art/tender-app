"""Native selection and versioned evidence binding, short owned transactions."""

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_calibration as shape
from packages.package_model_live import producer
from packages.package_model_registry import artifact


class Service:
    def __init__(self, transactions, executor, *, enabled=False):
        self.transactions, self.executor, self.enabled = transactions, executor, enabled

    def freeze(self, actor, model, expected_protocol_digest, key):
        artifact.files.command(key)
        artifact.files.checksum(expected_protocol_digest)
        with self.transactions() as tx:
            return tx.freeze(actor, model, expected_protocol_digest, key, producer.contract())

    def execute(self, actor, body):
        if self.enabled is not True:
            artifact.fail()
        keys = {
            "version",
            "command_id",
            "route_id",
            "action",
            "expected_revision",
            "producer_method_digest",
        }
        shape.exact(body, keys | ({"config"} if body.get("action") == "activate" else set()))
        if (
            body["version"] != "package-business-shadow-command/1"
            or body["action"] not in {"activate", "observe", "rollback"}
            or type(body["expected_revision"]) is not int
            or not 0 <= body["expected_revision"] < 2**53
        ):
            artifact.fail()
        for k in ("command_id", "route_id"):
            artifact.files.command(body[k])
        if body["action"] == "activate":
            config = body["config"]
            shape.exact(
                config,
                {
                    "candidate_model_id",
                    "fallback_model_id",
                    "intent_id",
                    "reference",
                    "binding_digest",
                },
            )
            for k in ("candidate_model_id", "fallback_model_id", "intent_id"):
                artifact.files.command(config[k])
            shape.exact(config["reference"], shape.REFERENCE)
            artifact.files.checksum(config["binding_digest"])
            if (
                config["candidate_model_id"] == config["fallback_model_id"]
                or body["expected_revision"] != 0
            ):
                artifact.fail()
        pinned_body = digest(body)
        with self.transactions() as tx:
            prior = tx.replay(actor, body)
            if prior is not None:
                return prior
            if body["producer_method_digest"] != producer.method_digest():
                artifact.fail()
            packet = tx.prepare(actor, body)
        pinned = digest(packet)
        result = self.executor(packet)
        if digest(packet) != pinned or digest(body) != pinned_body:
            artifact.fail()
        with self.transactions() as tx:
            return tx.commit(actor, body, pinned, result)
