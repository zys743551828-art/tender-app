"""API authorization and publication; workers never receive API credentials."""

from pathlib import Path

from packages.domain.errors import DomainError
from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_model_certification.application import Certificates
from packages.package_model_certification.policy import method_digest as cert_method
from packages.package_model_registry.artifact import fail
from packages.package_prediction.application import Predictions, method_digest
from packages.storage.private_cas import sha

HANDLER = "package-prediction/1"
STEP = "compute-package-prediction"


def task_method():
    return digest(
        {
            "version": HANDLER,
            "sources": {
                p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))
            },
        }
    )


def authorize(tx, actor, bid, scope, certificate):
    packet = tx.prepare(actor, bid, scope, certificate, method_digest(), cert_method())
    if not Certificates._view(packet["authority"], tx.now())["eligible"]:
        fail()
    return packet


class Jobs:
    def __init__(self, transactions, store):
        self.transactions, self.store = transactions, store

    def submit(self, actor, bid, scope, certificate, command):
        body = {
            "actor": str(actor),
            "bid": str(bid),
            "scope": str(scope),
            "certificate": str(certificate),
            "command": str(command),
        }
        with self.transactions(body) as tx:
            old = tx.job(body)
            if old is not None:
                return tx.view(old)
            packet = authorize(tx, actor, bid, scope, certificate)
            if tx.read(actor, bid, scope, command, method_digest(), cert_method()) is not None:
                fail()
        frozen = {
            "schema": HANDLER,
            "task_method": task_method(),
            "body": body,
            "packet": packet,
            "prediction_method": method_digest(),
            "certificate_method": cert_method(),
        }
        reference = self.store.put(frozen)
        with self.transactions(body) as tx:
            old = tx.job(body)
            if old is not None:
                return tx.view(old)
            if digest(authorize(tx, actor, bid, scope, certificate)) != digest(packet):
                fail()
            return tx.enqueue(body, reference, digest(packet))

    def read(self, actor, bid, scope, command):
        body = {"actor": str(actor), "bid": str(bid), "scope": str(scope), "command": str(command)}
        with self.transactions(body) as tx:
            job = tx.job(body)
            if job is None:
                fail()
            return tx.view(job)

    def advance(self, actor, bid, scope, command):
        body = {"actor": str(actor), "bid": str(bid), "scope": str(scope), "command": str(command)}
        with self.transactions(body) as tx:
            job = tx.job(body)
            if job is None:
                fail()
            view = tx.view(job)
            if view["state"] != "awaiting_publication":
                return view
        try:
            with self.transactions(job["body"]) as tx:
                tx.publishable(job)
                output = tx.output(job)
                b = job["body"]
                if (
                    digest(authorize(tx, b["actor"], b["bid"], b["scope"], b["certificate"]))
                    != job["authority_digest"]
                ):
                    fail()
            frozen = self.store.get(job["input_ref"])
            result = self.store.get(output["result_ref"])
            if (
                frozen["schema"] != HANDLER
                or frozen["task_method"] != task_method()
                or frozen["body"] != job["body"]
                or digest(frozen["packet"]) != job["authority_digest"]
                or frozen["prediction_method"] != method_digest()
                or frozen["certificate_method"] != cert_method()
                or output["input_ref"] != job["input_ref"]
            ):
                fail()

            def consume(packet):
                if digest(packet) != result["packet_digest"]:
                    fail()
                return result

            # Existing prediction consumer performs input/model/interval checks and
            # the final native certificate recheck. The wrapper also fences publication.
            Predictions(self.transactions(job["body"], publishing=job), consume).execute(
                actor, bid, scope, job["body"]["certificate"], command
            )
            with self.transactions(job["body"], publishing=job)() as tx:
                tx.mark_published(job)
        except (DomainError, GovernanceError) as error:
            if getattr(error, "retryable", False):
                raise
            with self.transactions(job["body"]) as tx:
                return tx.block(job)
        return self.read(actor, bid, scope, command)

    def cancel(self, actor, bid, scope, command):
        body = {"actor": str(actor), "bid": str(bid), "scope": str(scope), "command": str(command)}
        with self.transactions(body) as tx:
            job = tx.job(body)
            if job is None:
                fail()
            return tx.cancel(job)
