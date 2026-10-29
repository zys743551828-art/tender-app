"""Controlled selection, actual inference, then atomic route transition."""

from pathlib import Path
from typing import Protocol

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_calibration as shape
from packages.model_governance import package_feature_handoff as files
from packages.package_model_observation import execution
from packages.package_model_registry import artifact
from packages.storage.private_cas import sha

VERSION = "package-internal-route-command/1"
NATIVE_SQL_VERSION = "package-internal-route-sql/2"
CONFIG = {
    "candidate_model_id",
    "candidate_artifact_digest",
    "fallback_model_id",
    "fallback_artifact_digest",
    "admission_id",
    "reference",
    "observation_method_digest",
}


def method_digest():
    sql = Path(__file__).resolve().parents[2] / "deploy/sql/package-model-route-v2.sql"
    return digest(
        {
            "version": VERSION,
            "native_sql_version": NATIVE_SQL_VERSION,
            "application": sha(Path(__file__).read_bytes()),
            "sql": sha(sql.read_bytes()),
            "observation": execution.method_digest(),
        }
    )


def validate(request):
    keys = {"version", "command_id", "route_id", "action", "expected_revision", "method_digest"}
    shape.exact(request, keys | ({"config"} if request.get("action") == "activate" else set()))
    if request["version"] != VERSION or request["action"] not in {
        "activate",
        "consume",
        "rollback",
    }:
        artifact.fail()
    for key in ("command_id", "route_id"):
        files.command(request[key])
    files.checksum(request["method_digest"])
    if (
        type(request["expected_revision"]) is not int
        or not 0 <= request["expected_revision"] < 2**53
    ):
        artifact.fail()
    if request["action"] == "activate":
        config = request["config"]
        shape.exact(config, CONFIG)
        for key in ("candidate_model_id", "fallback_model_id", "admission_id"):
            files.command(config[key])
        for key in (
            "candidate_artifact_digest",
            "fallback_artifact_digest",
            "observation_method_digest",
        ):
            files.checksum(config[key])
        shape.exact(config["reference"], shape.REFERENCE)
        if (
            config["candidate_model_id"] == config["fallback_model_id"]
            or request["expected_revision"] != 0
        ):
            artifact.fail()


class Transaction(Protocol):
    def replay(self, actor, request): ...
    def prepare(self, actor, request): ...
    def commit(self, actor, request, packet_digest, result): ...


class Routes:
    def __init__(self, transactions, executor):
        self.transactions, self.executor = transactions, executor

    def execute(self, actor, request):
        validate(request)
        pinned_request = digest(request)
        with self.transactions() as tx:
            previous = tx.replay(actor, request)
            if previous is not None:
                return previous
            if request["method_digest"] != method_digest():
                artifact.fail()
            packet = tx.prepare(actor, request)
        pinned_packet = digest(packet)
        result = self.executor(packet["source"], packet["observation_request"])
        if digest(packet) != pinned_packet or digest(request) != pinned_request:
            artifact.fail()
        with self.transactions() as tx:
            return tx.commit(actor, request, pinned_packet, result)
