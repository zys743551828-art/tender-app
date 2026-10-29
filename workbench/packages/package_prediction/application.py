"""Two short authority transactions surrounding private material verification/CPU."""

from decimal import Decimal
from pathlib import Path
from typing import Protocol

from packages.domain.review_identity import digest
from packages.package_model_certification import policy as certification
from packages.package_model_certification.application import Certificates
from packages.package_model_live import producer
from packages.package_model_registry import artifact
from packages.storage.private_cas import sha

VERSION = "package-formal-prediction/1"


def method_digest():
    root = Path(__file__).parent
    return digest(
        {
            "version": VERSION,
            "sources": {p.name: sha(p.read_bytes()) for p in sorted(root.glob("*.py"))},
            "sql": sha((root.parents[1] / "deploy/sql/package-formal-prediction.sql").read_bytes()),
            "certification": certification.method_digest(),
            "producer": producer.method_digest(),
        }
    )


class Transaction(Protocol):
    def prepare(self, actor, bid, scope, certificate, method, cert_method): ...
    def read(self, actor, bid, scope, command, method, cert_method): ...
    def commit(
        self, actor, bid, scope, certificate, command, pinned, result, method, cert_method
    ): ...
    def now(self): ...


class Predictions:
    def __init__(self, transactions, executor=None):
        self.transactions, self.executor = transactions, executor

    def read(self, actor, bid, scope, command):
        with self.transactions() as tx:
            return tx.read(
                actor, bid, scope, command, method_digest(), certification.method_digest()
            )

    def execute(self, actor, bid, scope, certificate, command):
        for value in (bid, scope, certificate, command):
            artifact.files.command(str(value))
        method, cert_method = method_digest(), certification.method_digest()
        with self.transactions() as tx:
            prior = tx.read(actor, bid, scope, command, method, cert_method)
            if prior is not None:
                if prior["certificate_id"] != str(certificate):
                    artifact.fail()
                return prior
            packet = tx.prepare(actor, bid, scope, certificate, method, cert_method)
            if not Certificates._view(packet["authority"], tx.now())["eligible"]:
                artifact.fail()
        if self.executor is None:
            artifact.fail()
        pinned = digest(packet)
        computation = {
            "source": packet["authority"]["source"]["current_source"],
            "artifact": packet["authority"]["source"]["model"],
            "reference": packet["reference"],
        }
        expected = digest(computation)
        value = self.executor(computation)
        if (
            value.get("schema") != "package-business-shadow-result/1"
            or value.get("formal_eligibility") != "unavailable"
            or value.get("certification_issued") is not False
            or digest(packet) != pinned
            or digest(computation) != expected
            or value["packet_digest"] != expected
            or value["mode"] != "live"
            or value["source_digest"] != digest(computation["source"])
            or value["artifact_digest"] != digest(computation["artifact"])
            or value["model_id"] != computation["artifact"]["model_id"]
            or value["input_digest"] != computation["source"]["input_digest"]
            or value["producer_method_digest"] != producer.method_digest()
        ):
            artifact.fail()
        artifact.files.checksum(value["projection_digest"])
        number = certification.admission.number(value["value"])
        if not 0 <= number <= 100:
            artifact.fail()
        model = packet["authority"]["source"]["model"]["source"]["candidate"]
        radius = certification.admission.number(model["intervals"]["0.8"]["radius"])
        if radius < 0:
            artifact.fail()
        result = {
            "schema": VERSION,
            "method_digest": method,
            "certificate_id": str(certificate),
            "model_id": value["model_id"],
            "artifact_digest": value["artifact_digest"],
            "input_digest": value["input_digest"],
            "projection_digest": value["projection_digest"],
            "value": value["value"],
            "maximum": "100",
            "interval_level": "0.8",
            "low": format(max(Decimal(0), number - radius), "f"),
            "high": format(min(Decimal(100), number + radius), "f"),
            "training_groups": model["groups"],
            "evaluation_project_mae": packet["authority"]["source"]["report"]["report"]["report"][
                "project_mae"
            ],
            "source_digest": pinned,
        }
        with self.transactions() as tx:
            fresh = tx.prepare(actor, bid, scope, certificate, method, cert_method)
            if (
                digest(fresh) != pinned
                or not Certificates._view(fresh["authority"], tx.now())["eligible"]
            ):
                artifact.fail()
            return tx.commit(
                actor, bid, scope, certificate, command, pinned, result, method, cert_method
            )
