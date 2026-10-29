"""Consume exact completed business judgments, never request another model call."""

from pathlib import Path

from packages.domain.review_identity import digest
from packages.model_governance import material_execution_dispatch as dispatch
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_cpu as cpu
from packages.package_model_registry import artifact
from packages.storage.private_cas import PrivateContentStore, sha

VERSION = "package-business-shadow-producer/1"


def method_digest():
    root = Path(__file__).parent
    return digest(
        {
            "version": VERSION,
            "sources": {p.name: sha(p.read_bytes()) for p in sorted(root.glob("*.py"))},
            "sql": sha((root.parents[1] / "deploy/sql/package-business-shadow.sql").read_bytes()),
            "dispatch": dispatch.method_digest(),
            "registry": artifact.method_digest(),
            "handoff": handoff.method_digest(),
        }
    )


def contract():
    return {
        "schema": "package-business-evidence-binding/1",
        "producer_method_digest": method_digest(),
        "material_contract": handoff.VERSION,
        "observation_schema": "package-business-shadow-result/1",
        "route_command_schema": "package-business-shadow-command/1",
    }


def consume(packet, store, index):
    source, reference = packet["source"], packet["reference"]
    doc = artifact.validate(packet["artifact"])
    if (
        source.get("producer_method_digest") != method_digest()
        or source["schema"] != "package-business-shadow-source/1"
        or source["mode"]
        not in {
            "synthetic",
            "live",
        }
    ):
        artifact.fail()
    loaded = handoff.load(store, index, **reference)
    if (
        loaded.bundle.metadata["digest"] != source["input_digest"]
        or loaded.bundle.context.metadata["digest"] != source["context_digest"]
    ):
        artifact.fail()
    metadata = loaded.bundle.context.metadata
    if (
        any(metadata[k] != source[k] for k in ("bid_id", "scope_id", "scope_digest"))
        or loaded.bundle.context.origin.material["scope"]["manifest"] != source["scope_manifest"]
    ):
        artifact.fail()
    expected = {row["document_version_id"]: row for row in source["originals"]}
    originals = loaded.bundle.context.origin.originals
    if len(expected) != len(source["originals"]) or set(expected) != set(originals):
        artifact.fail()
    if any(
        sha(blob) != expected[key]["digest"] or len(blob) != expected[key]["byte_size"]
        for key, blob in originals.items()
    ):
        artifact.fail()
    # Source is produced by the native ledger, not supplied by the HTTP caller.
    expected_attempts = {(row["rule_id"], row["slot"]): row for row in source["attempts"]}
    if len(expected_attempts) != len(source["attempts"]) or len(loaded.attempts) != len(
        expected_attempts
    ):
        artifact.fail()
    seen = set()
    for attempt in loaded.attempts:
        key = (attempt.rule_id, attempt.slot)
        native = expected_attempts.get(key)
        generation = attempt.generation
        if (
            key in seen
            or native is None
            or generation is None
            or attempt.attempt != 1
            or attempt.call_id != native["attempt_id"]
            or attempt.request.receipt["request_digest"] != native["request_digest"]
            or generation.raw_response_digest != native["raw_response_digest"]
            or generation.response_id != native["response_id"]
        ):
            artifact.fail()
        seen.add(key)
    projected = training.project(loaded)
    candidate = doc["source"]["candidate"]
    # Synthetic fixture/model can never become a real source just via CAS origin text.
    if source["mode"] == "live" and doc["source"]["origin"] != "external_evidence":
        artifact.fail()
    value = training.predict(candidate["model"], projected["values"])
    return cpu.wire(
        {
            "schema": "package-business-shadow-result/1",
            "producer_method_digest": method_digest(),
            "mode": source["mode"],
            "source_digest": digest(source),
            "packet_digest": digest(packet),
            "model_id": doc["model_id"],
            "artifact_digest": digest(doc),
            "input_digest": projected["input_digest"],
            "projection_digest": projected["digest"],
            "value": value,
            "formal_eligibility": "unavailable",
            "certification_issued": False,
        }
    )


class Executor:
    def __init__(self, store, index):
        self.store, self.index = store, index

    def __call__(self, packet):
        with PrivateContentStore(self.store) as store:
            return consume(packet, store, self.index)
