"""Inert versioned ridge artifacts; validated identities never confer eligibility."""

from copy import deepcopy
from math import ceil
from pathlib import Path
from uuid import UUID, uuid5

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_handoff as files
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import GovernanceError, finite
from packages.storage.private_cas import sha

VERSION = "registered-package-score-artifact/1"
SNAPSHOT = "package-score-registration-source/1"
MAX_BYTES = 2 * 1024 * 1024
SOURCE_KEYS = {
    "schema",
    "training_job_id",
    "cohort_id",
    "cohort_digest",
    "membership_digest",
    "protocol_digest",
    "result_digest",
    "candidate",
    "candidate_digest",
    "origin",
}
CANDIDATE_KEYS = {
    "version",
    "method_digest",
    "feature_schema",
    "feature_names",
    "origin",
    "membership_digest",
    "projection_digest",
    "source_digest",
    "status",
    "unavailable_reasons",
    "groups",
    "model",
    "model_digest",
    "selection",
    "intervals",
    "features_used_for_fit",
    "formal_prediction",
    "final_test_consumption",
} | set(handoff.FLAGS)


def fail():
    raise GovernanceError("PACKAGE_REGISTERED_ARTIFACT_INVALID", "Frozen package artifact rejected")


def method_digest():
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "training_method": training.method()["digest"],
        }
    )


def feature_contract():
    return {
        "schema": training.SCHEMA,
        "names": list(training.FEATURES),
        "feature_scale": "unit_interval",
        "target_scale": "normalized_0_100",
    }


def candidate(value):
    if type(value) is not dict or set(value) != CANDIDATE_KEYS:
        fail()
    if (
        value["version"] != training.VERSION
        or value["method_digest"] != training.method()["digest"]
        or value["feature_schema"] != training.SCHEMA
        or value["feature_names"] != training.FEATURES
        or value["origin"] not in {"synthetic", "external_evidence"}
        or value["status"] != "research_candidate"
        or value["unavailable_reasons"] != []
        or value["features_used_for_fit"] is not True
        or value["formal_prediction"] is not None
        or value["final_test_consumption"] != "not_implemented"
        or any(value[k] is not False for k in handoff.FLAGS)
    ):
        fail()
    for key in ("membership_digest", "projection_digest", "source_digest", "model_digest"):
        files.checksum(value[key])
    model = value["model"]
    if type(model) is not dict or digest(model) != value["model_digest"]:
        fail()
    files.checksum(model.get("training_digest"))
    training.predict(model, [0] * len(training.FEATURES))
    groups = value["groups"]
    if type(groups) is not dict or set(groups) != set(training.MIN_GROUPS):
        fail()
    for key, minimum in training.MIN_GROUPS.items():
        if type(groups[key]) is not int or not minimum <= groups[key] <= 1000000:
            fail()
    selection = value["selection"]
    if (
        type(selection) is not dict
        or set(selection) != {"selected_alpha", "development_project_mae", "refit_with_development"}
        or selection["refit_with_development"] is not False
    ):
        fail()
    losses = selection["development_project_mae"]
    if type(losses) is not dict or set(losses) != set(training.ALPHAS):
        fail()
    losses = {k: finite(v, lower=0, upper=100) for k, v in losses.items()}
    chosen = min(training.ALPHAS, key=lambda k: (losses[k], training.ALPHAS.index(k)))
    if chosen != selection["selected_alpha"] or model["alpha"] != chosen:
        fail()
    intervals = value["intervals"]
    if type(intervals) is not dict or set(intervals) != {"0.8", "0.9"}:
        fail()
    for level, entry in intervals.items():
        if type(entry) is not dict or set(entry) != {"radius", "groups", "rank"}:
            fail()
        if (
            type(entry["groups"]) is not int
            or entry["groups"] != groups["calibration"]
            or type(entry["rank"]) is not int
            or entry["rank"] != ceil((entry["groups"] + 1) * float(level))
        ):
            fail()
        finite(entry["radius"], lower=0, upper=100)
    if finite(intervals["0.8"]["radius"]) > finite(intervals["0.9"]["radius"]):
        fail()


def build(source):
    try:
        if type(source) is not dict or set(source) != SOURCE_KEYS or source["schema"] != SNAPSHOT:
            fail()
        for key in (
            "cohort_digest",
            "membership_digest",
            "protocol_digest",
            "result_digest",
            "candidate_digest",
        ):
            files.checksum(source[key])
        for key in ("training_job_id", "cohort_id"):
            files.command(source[key])
        candidate(source["candidate"])
        if (
            digest(source["candidate"]) != source["candidate_digest"]
            or source["origin"] != source["candidate"]["origin"]
            or source["membership_digest"] != source["candidate"]["membership_digest"]
        ):
            fail()
        value = {
            "schema": VERSION,
            "model_id": str(uuid5(UUID(source["training_job_id"]), VERSION)),
            "adapter_method_digest": method_digest(),
            "feature_contract": feature_contract(),
            "source": deepcopy(source),
            "research_only": True,
            "formal_eligibility": "unavailable",
        }
        if len(canonical(value)) > MAX_BYTES:
            fail()
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        fail()


def validate(value):
    try:
        if (
            type(value) is not dict
            or "source" not in value
            or canonical(value) != canonical(build(value["source"]))
        ):
            fail()
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        fail()


def load(raw, expected_digest):
    if (
        not isinstance(raw, bytes)
        or not 0 < len(raw) <= MAX_BYTES
        or sha(raw) != files.checksum(expected_digest)
    ):
        fail()
    value = files.decode(raw)
    if canonical(value) != raw:
        fail()
    return validate(value)


def consume(document, store, artifact_dir, reference, *, expected_input_digest):
    """Reload original /3 material, never accept caller-supplied feature vectors."""
    validate(document)
    if reference.get("expected_input_digest") != files.checksum(expected_input_digest):
        fail()
    loaded = handoff.load(store, artifact_dir, **reference)
    projected = training.project(loaded)
    if projected["input_digest"] != expected_input_digest:
        fail()
    value = training.predict(document["source"]["candidate"]["model"], projected["values"])
    intervals = {
        level: [max(0, value - finite(item["radius"])), min(100, value + finite(item["radius"]))]
        for level, item in document["source"]["candidate"]["intervals"].items()
    }
    return cpu.wire(
        {
            "schema": "registered-package-research-prediction/1",
            "model_id": document["model_id"],
            "artifact_digest": digest(document),
            "adapter_method_digest": method_digest(),
            "input_digest": expected_input_digest,
            "projection_digest": projected["digest"],
            "value": value,
            "intervals": intervals,
            "scale": "normalized_0_100",
            "research_only": True,
            "formal_eligibility": "unavailable",
            **handoff.FLAGS,
        }
    )
