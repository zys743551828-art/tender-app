"""Explicit business thresholds, separate from candidate training hyperparameters."""

import math
from typing import Protocol


class AdmissionError(ValueError):
    pass


VERSION = "score-business-admission-protocol/1"
FAMILY = "registered-score-artifact/1"
BOUNDS = {
    "maximum_project_mae": (0, 100),
    "minimum_paired_baseline_gain": (-100, 100),
    "minimum_success_coverage": (0, 1),
    "minimum_interval_coverage": (0, 1),
    "interval_level": (0, 1),
}


def validate(document):
    if type(document) is not dict or set(document) != {
        "schema",
        "artifact_family",
        "baseline",
        "thresholds",
    }:
        raise AdmissionError("ADMISSION_PROTOCOL_SHAPE")
    if document["schema"] != VERSION or document["artifact_family"] != FAMILY:
        raise AdmissionError("ADMISSION_PROTOCOL_VERSION")
    if document["baseline"] not in ("mean", "median"):
        raise AdmissionError("ADMISSION_BASELINE_UNSUPPORTED")
    thresholds = document["thresholds"]
    if type(thresholds) is not dict or set(thresholds) != set(BOUNDS):
        raise AdmissionError("ADMISSION_THRESHOLDS_REQUIRED")
    for name, (lower, upper) in BOUNDS.items():
        value = thresholds[name]
        if (
            type(value) not in (int, float)
            or not (lower <= value <= upper and math.isfinite(value))
            or not lower <= value <= upper
        ):
            raise AdmissionError("ADMISSION_THRESHOLD_INVALID")
    if thresholds["interval_level"] in (0, 1):
        raise AdmissionError("ADMISSION_INTERVAL_INVALID")
    # Copy so callers cannot mutate the validated threshold object during orchestration.
    return dict(document, thresholds=dict(thresholds))


class Store(Protocol):
    def freeze(self, cohort_id, actor_id, document, key, reason): ...
    def read(self, cohort_id, actor_id): ...


class AdmissionProtocols:
    def __init__(self, store: Store):
        self.store = store

    def freeze(self, cohort_id, actor_id, document, key, reason):
        value = validate(document)
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or not key.strip():
            raise AdmissionError("ADMISSION_IDEMPOTENCY_REQUIRED")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4000:
            raise AdmissionError("ADMISSION_REASON_REQUIRED")
        return self.store.freeze(cohort_id, actor_id, value, key, reason)

    def read(self, cohort_id, actor_id):
        return self.store.read(cohort_id, actor_id)
