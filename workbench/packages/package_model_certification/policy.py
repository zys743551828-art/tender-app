"""Strict existing thresholds plus identity/lifetime checks, no default limits."""

from pathlib import Path

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_calibration as shape
from packages.package_model_admission import policy as admission
from packages.package_model_live import producer
from packages.package_model_registry import artifact
from packages.storage.private_cas import sha

VERSION = "package-model-certification/1"


def method_digest():
    root = Path(__file__).parent
    return digest(
        {
            "version": VERSION,
            "sources": {p.name: sha(p.read_bytes()) for p in sorted(root.glob("*.py"))},
            "sql": sha(
                (root.parents[1] / "deploy/sql/package-model-certification.sql").read_bytes()
            ),
            "producer": producer.method_digest(),
            "admission": sha(Path(admission.__file__).read_bytes()),
        }
    )


def request(body):
    shape.exact(body, {"shadow_event_id", "rollback_event_id", "valid_until", "reason"})
    for key in ("shadow_event_id", "rollback_event_id"):
        artifact.files.command(body[key])
    if body["shadow_event_id"] == body["rollback_event_id"]:
        admission.fail()
    admission.instant(body["valid_until"])
    reason(body["reason"])


def reason(value):
    if type(value) is not str or not 1 <= len(value.strip()) <= 4000:
        admission.fail()


def assess(packet, model_id, body, now):
    """Only a native-channel source may supply packet; never an HTTP body."""
    try:
        if packet["schema"] != "package-certification-source/1":
            admission.fail()
        doc = artifact.validate(packet["model"])
        fallback = artifact.validate(packet["fallback_model"])
        report = packet["report"]
        metrics = admission.assess(report)
        binding = packet["binding"]
        if (
            doc["model_id"] != str(model_id)
            or doc["source"]["origin"] != "external_evidence"
            or fallback["source"]["origin"] != "external_evidence"
            or not metrics["all_declared_metric_checks_pass"]
            or metrics["origin"] != "external_evidence"
        ):
            admission.fail()
        if (
            binding["document"]["schema"] != "score-business-admission-protocol/3"
            or digest(binding["document"]) != binding["digest"]
            or binding["document"]["protocol"] != report["protocol"]
            or binding["document"]["protocol_digest"] != report["protocol_digest"]
            or binding["document"]["evidence_contract"] != producer.contract()
        ):
            admission.fail()
        if report["protocol"]["binding"]["model_id"] != str(model_id) or report["protocol"][
            "binding"
        ]["artifact_digest"] != digest(doc):
            admission.fail()
        shadow, rollback = packet["shadow"], packet["rollback"]
        if (
            shadow["command_id"] != body["shadow_event_id"]
            or rollback["command_id"] != body["rollback_event_id"]
            or shadow["route_id"] != rollback["route_id"]
            or shadow["revision"] >= rollback["revision"]
            or rollback["action"] != "rollback"
            or rollback["previous_model_id"] != str(model_id)
            or shadow["selected_model_id"] != str(model_id)
            or rollback["selected_model_id"] != fallback["model_id"]
            or fallback["model_id"] == str(model_id)
        ):
            admission.fail()
        if shadow["source"] != rollback["source"] or shadow["source"] != packet["current_source"]:
            admission.fail()
        src = packet["current_source"]
        if src["mode"] != "live" or src["producer_method_digest"] != producer.method_digest():
            admission.fail()
        for event, model in ((shadow, doc), (rollback, fallback)):
            value = event["result"]
            if (
                value["schema"] != "package-business-shadow-result/1"
                or value["mode"] != "live"
                or value["producer_method_digest"] != producer.method_digest()
                or value["source_digest"] != digest(src)
                or value["input_digest"] != src["input_digest"]
                or value["model_id"] != model["model_id"]
                or value["artifact_digest"] != digest(model)
                or value["formal_eligibility"] != "unavailable"
                or value["certification_issued"] is not False
            ):
                admission.fail()
        instant = admission.instant
        if not instant(binding["frozen_at"]) < instant(report["exposure_at"]) or not instant(
            binding["frozen_at"]
        ) < instant(packet["captured_at"]) <= instant(shadow["created_at"]) <= instant(
            rollback["created_at"]
        ) <= instant(now) < instant(body["valid_until"]) <= instant(packet["evidence_valid_until"]):
            admission.fail()
        return {
            "artifact_digest": digest(doc),
            "protocol_digest": binding["digest"],
            "observation_input_digest": src["input_digest"],
            "feature_contract": doc["feature_contract"],
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        admission.fail()
