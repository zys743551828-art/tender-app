"""Explicit test-only acceptance lane over the existing durable prediction task."""

from pathlib import Path

from packages.domain.errors import DomainError
from packages.domain.review_identity import digest
from packages.package_model_certification.policy import method_digest as certification_method
from packages.package_model_live.producer import Executor
from packages.package_prediction.application import method_digest as prediction_method
from packages.package_prediction_tasks.application import HANDLER, task_method
from packages.storage.private_cas import sha


def method_digest():
    root = Path(__file__).parent
    return digest(
        {
            "version": "prediction-sandbox/1",
            "sources": {p.name: sha(p.read_bytes()) for p in sorted(root.glob("*.py"))},
            "sql": sha((root.parents[1] / "deploy/sql/prediction-sandbox.sql").read_bytes()),
            "task": task_method(),
            "prediction": prediction_method(),
        }
    )


def reject():
    raise DomainError("PREDICTION_SANDBOX_REJECTED", "仅测试资格、材料或运行环境已失效", 409)


class Sandbox:
    """Opt-in host injection. Never constructs or calls a production certificate service."""

    def __init__(self, transactions, objects, executor):
        if type(executor) is not Executor:
            reject()
        self.transactions = transactions
        self.objects, self.executor = objects, executor

    @staticmethod
    def call(tx, body, action, payload):
        return tx.sandbox(body, action, payload)

    @classmethod
    def active(cls, tx, body):
        value = cls.call(tx, body, "prepare", {})
        if (
            value["state"] != "active"
            or value["request"]["method_digest"] != method_digest()
            or value["scope_id"] != body["scope"]
        ):
            reject()
        return value

    def packet(self, reference):
        try:
            packet = self.objects.get(reference)
            if (
                set(packet) != {"source", "artifact", "reference"}
                or packet["source"]["mode"] != "synthetic"
            ):
                reject()
            result = self.executor(packet)
            if (
                result["mode"] != "synthetic"
                or result["formal_eligibility"] != "unavailable"
                or result["certification_issued"] is not False
                or result["packet_digest"] != digest(packet)
            ):
                reject()
            return packet
        except (KeyError, TypeError, ValueError):
            reject()

    def issue(self, actor, bid, command, source_ref, valid_until):
        packet = self.packet(source_ref)
        source = packet["source"]
        if source["bid_id"] != str(bid):
            reject()
        body = {"actor": str(actor), "bid": str(bid)}
        request = {
            "command_id": str(command),
            "scope_id": source["scope_id"],
            "source_ref": source_ref,
            "packet_digest": digest(packet),
            "method_digest": method_digest(),
            "valid_until": valid_until,
        }
        with self.transactions(body) as tx:
            tx.writable(bid)
            return self.call(tx, body, "issue", request)

    def submit(self, body):
        with self.transactions(body) as tx:
            certificate = self.active(tx, body)
            old = tx.job(body)
            if old is not None:
                return tx.view(old)
        packet = self.packet(certificate["request"]["source_ref"])
        if digest(packet) != certificate["request"]["packet_digest"]:
            reject()
        authority = {
            "authority": {
                "source": {"current_source": packet["source"], "model": packet["artifact"]}
            },
            "reference": packet["reference"],
        }
        frozen = {
            "schema": HANDLER,
            "task_method": task_method(),
            "body": body,
            "packet": authority,
            "prediction_method": prediction_method(),
            "certificate_method": certification_method(),
        }
        reference = self.objects.put(frozen)
        with self.transactions(body) as tx:
            if self.active(tx, body) != certificate:
                reject()
            old = tx.job(body)
            return (
                tx.view(old) if old is not None else tx.enqueue(body, reference, digest(authority))
            )

    def read(self, body):
        with self.transactions(body) as tx:
            certificate = self.call(tx, body, "result", {"command_id": body["command"]})
            job = tx.job(body)
            if job is None:
                reject()
            view = tx.view(job)
            valid = (
                certificate["state"] == "active"
                and certificate["request"]["method_digest"] == method_digest()
                and certificate["scope_id"] == body["scope"]
            )
            result = certificate["result"] if valid and view["state"] != "cancelled" else None
            return {
                "schema": "prediction-sandbox-task/1",
                "test_only": True,
                "production_eligible": False,
                "task": view,
                "state": "invalid" if not valid else "test_published" if result else view["state"],
                "result": result,
            }

    def advance(self, body):
        with self.transactions(body) as tx:
            certificate = self.active(tx, body)
            job = tx.job(body)
            if job is None:
                reject()
            tx.publishable(job)
            output = tx.output(job)
        packet = self.packet(certificate["request"]["source_ref"])
        frozen, result = self.objects.get(job["input_ref"]), self.objects.get(output["result_ref"])
        if (
            frozen["body"] != body
            or frozen["task_method"] != task_method()
            or digest(frozen["packet"]) != job["authority_digest"]
            or digest(packet) != certificate["request"]["packet_digest"]
            or self.executor(packet) != result
        ):
            reject()
        with self.transactions(body) as tx:
            self.active(tx, body)
            tx.publishable(job)
            if tx.output(job) != output:
                reject()
            self.call(
                tx,
                body,
                "publish",
                {
                    "command_id": body["command"],
                    "operation_id": job["operation_id"],
                    "result_ref": output["result_ref"],
                    "value": str(result["value"]),
                    "method_digest": method_digest(),
                },
            )
        return self.read(body)

    def revoke(self, body, command, reason):
        with self.transactions(body) as tx:
            return self.call(tx, body, "revoke", {"command_id": str(command), "reason": reason})

    def cancel(self, body):
        with self.transactions(body) as tx:
            self.call(tx, body, "prepare", {})
            job = tx.job(body)
            if job is None:
                reject()
            if self.call(tx, body, "result", {"command_id": body["command"]})["result"]:
                reject()
            return tx.cancel(job)
