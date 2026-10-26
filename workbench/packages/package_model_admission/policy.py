"""Explicit /2 thresholds and report comparisons, never a certification issuer."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from packages.model_admission.application import BOUNDS
from packages.model_governance import package_feature_evaluation as evaluation
from packages.model_governance import package_feature_training as training
from packages.model_governance.common import GovernanceError
from packages.package_model_registry import artifact

VERSION = "score-business-admission-protocol/2"
BINDING = {
    "model_id",
    "artifact_digest",
    "cohort_id",
    "cohort_digest",
    "membership_digest",
    "candidate_digest",
    "training_method_digest",
    "input_reference_digest",
    "final_manifest_digest",
}


def fail():
    raise GovernanceError("PACKAGE_ADMISSION_INVALID", "Bound business protocol or report rejected")


def number(value):
    if type(value) is not str or not 1 <= len(value) <= 80:
        fail()
    try:
        result = Decimal(value)
    except InvalidOperation:
        fail()
    if not result.is_finite():
        fail()
    return result


def validate(document):
    if type(document) is not dict or set(document) != {
        "schema",
        "artifact_family",
        "binding",
        "baseline",
        "thresholds",
    }:
        fail()
    if document["schema"] != VERSION or document["artifact_family"] != artifact.VERSION:
        fail()
    if document["baseline"] not in ("mean", "median"):
        fail()
    binding = document["binding"]
    if type(binding) is not dict or set(binding) != BINDING:
        fail()
    for key, value in binding.items():
        if key in {"model_id", "cohort_id"}:
            artifact.files.command(value)
        else:
            artifact.files.checksum(value)
    values = document["thresholds"]
    if type(values) is not dict or set(values) != set(BOUNDS):
        fail()
    for key, (lower, upper) in BOUNDS.items():
        if not Decimal(lower) <= number(values[key]) <= Decimal(upper):
            fail()
    if values["interval_level"] not in {"0.8", "0.9"}:
        fail()
    return document


def instant(value):
    try:
        if type(value) is not str:
            fail()
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            fail()
        return result
    except ValueError:
        fail()


def assess(packet):
    """Only Native report_source/read_report packets belong here; not HTTP bodies."""
    try:
        if (
            type(packet) is not dict
            or set(packet)
            != {
                "schema",
                "protocol",
                "protocol_digest",
                "protocol_frozen_at",
                "exposure_at",
                "exposure_id",
                "evaluation_job_id",
                "result_digest",
                "report",
            }
            or packet["schema"] != "package-admission-native-report/1"
        ):
            fail()
        protocol = validate(packet["protocol"])
        if artifact.digest(protocol) != packet["protocol_digest"]:
            fail()
        for key in ("result_digest",):
            artifact.files.checksum(packet[key])
        for key in ("exposure_id", "evaluation_job_id"):
            artifact.files.command(packet[key])
        if instant(packet["protocol_frozen_at"]) >= instant(packet["exposure_at"]):
            fail()
        report = packet["report"]
        binding = protocol["binding"]
        if (
            report["version"] != evaluation.VERSION
            or report["method_digest"] != evaluation.method_digest()
            or report["freeze_method_digest"] != evaluation.frozen.method_digest()
            or report["candidate_digest"] != binding["candidate_digest"]
            or report["cohort_id"] != binding["cohort_id"]
            or report["membership_digest"] != binding["membership_digest"]
            or report["exposure_id"] != packet["exposure_id"]
            or binding["training_method_digest"] != training.method()["digest"]
            or report["origin"] not in {"synthetic", "external_evidence"}
            or report["research_only"] is not True
            or report["formal_prediction"] is not None
            or report["acceptance_decision"] != "unavailable"
            or type(report["provider_requests"]) is not int
            or report["provider_requests"] != 0
            or type(report["paid_calls"]) is not int
            or report["paid_calls"] != 0
        ):
            fail()
        metrics = report["report"]
        if type(metrics["denominator"]) is not int or metrics["denominator"] <= 0:
            fail()
        limit = protocol["thresholds"]
        measured = {
            "maximum_project_mae": metrics["project_mae"],
            "minimum_success_coverage": metrics["success_coverage"],
            "minimum_paired_baseline_gain": metrics["paired_baselines"][protocol["baseline"]][
                "gain"
            ],
            "minimum_interval_coverage": metrics["intervals"][limit["interval_level"]]["coverage"],
        }
        checks = {}
        for key, value in measured.items():
            lower, upper = BOUNDS[key]
            n = number(value)
            if not Decimal(lower) <= n <= Decimal(upper):
                fail()
            checks[key] = (
                n <= number(limit[key]) if key.startswith("maximum") else n >= number(limit[key])
            )
        return {
            "schema": "package-admission-metric-check/1",
            "checks": checks,
            "all_declared_metric_checks_pass": all(checks.values()),
            "origin": report["origin"],
            "snapshot_only": True,
            "formal_eligibility": "unavailable",
            "certification_issued": False,
            "missing_authorities": [
                "package_shadow_observation",
                "package_rollback_acceptance",
                "independent_certification",
            ],
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        fail()
