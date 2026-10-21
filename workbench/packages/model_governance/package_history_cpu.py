"""Frozen feature-free baselines for retrospective packages, never online calibration.

No invented zero feature vectors are passed to the old single-body trainer. The
shared project weighting, quantiles and grouped evaluation are reused directly.
"""

import hashlib
from collections import Counter, defaultdict
from decimal import Decimal
from math import ceil, fsum
from pathlib import Path

from packages.model_governance import evaluation, statistics
from packages.model_governance.common import GovernanceError, digest, finite, instant

VERSION = "package-history-project-baselines/1"
FIELDS = {
    "schema",
    "method",
    "families",
    "selection_metric",
    "tie_order",
    "refit_with_development",
    "interval_levels",
    "bootstrap_iterations",
    "seed",
    "group_spanning_policy",
}


def wire(value):
    """Stable decimal strings survive PostgreSQL JSON without float re-encoding."""
    if isinstance(value, float):
        return format(Decimal(str(finite(value))), "f")
    if isinstance(value, dict):
        return {key: wire(child) for key, child in value.items()}
    if isinstance(value, list):
        return [wire(child) for child in value]
    return value


def method():
    root = Path(__file__).resolve().parents[2]
    names = [
        "packages/model_governance/package_history_cpu.py",
        "packages/model_governance/common.py",
        "packages/model_governance/evaluation.py",
        "packages/model_governance/statistics.py",
    ]
    value = {
        "version": VERSION,
        "purpose": "retrospective_research",
        "features": "not_required_by_constant_baselines",
        "provider_requests": 0,
        "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
    }
    return value | {"digest": digest(value)}


def protocol(*, seed=17, bootstrap_iterations=1000):
    value = {
        "schema": "package-history-cpu-protocol/1",
        "method": method(),
        "families": ["mean", "median"],
        "selection_metric": "project_mae",
        "tie_order": ["mean", "median"],
        "refit_with_development": False,
        "interval_levels": [0.8, 0.9],
        "bootstrap_iterations": bootstrap_iterations,
        "seed": seed,
        "group_spanning_policy": "exclude",
    }
    validate_protocol(value)
    return value


def validate_protocol(value):
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or value["schema"] != "package-history-cpu-protocol/1"
        or value["method"] != method()
        or value["families"] != ["mean", "median"]
        or value["tie_order"] != ["mean", "median"]
        or value["selection_metric"] != "project_mae"
        or value["refit_with_development"] is not False
        or value["interval_levels"] != [0.8, 0.9]
        or value["group_spanning_policy"] != "exclude"
        or type(value["seed"]) is not int
        or not 0 <= value["seed"] <= 2147483647
        or type(value["bootstrap_iterations"]) is not int
        or not 100 <= value["bootstrap_iterations"] <= 10000
    ):
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_PROTOCOL_INVALID",
            "Exact separately frozen feature-free method required",
        )
    return digest(value)


def _rows(value):
    if not isinstance(value, list) or not value or len(value) > 10000:
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_MEMBERSHIP_INVALID", "Bounded nonempty membership required"
        )
    if len({r["id"] for r in value}) != len(value):
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_MEMBERSHIP_INVALID",
            "Repeated submissions cannot be independent samples",
        )
    for row in value:
        if row["purpose"] not in {"fit", "development", "calibration"}:
            raise GovernanceError(
                "PACKAGE_HISTORY_CPU_LABEL_LEAK", "Final and excluded labels cannot enter training"
            )
        finite(row["target"], lower=0, upper=100)
        if not row["project_id"] or not row["group_id"]:
            raise GovernanceError(
                "PACKAGE_HISTORY_CPU_GROUP_MISSING", "Frozen project and connected group required"
            )
    return value


def _constants(rows):
    counts = Counter(row["project_id"] for row in rows)
    weights = [1 / counts[row["project_id"]] for row in rows]
    targets = [finite(row["target"], lower=0, upper=100) for row in rows]
    mean = statistics.weighted_mean(targets, weights)
    pairs = sorted(zip(targets, weights, strict=True))
    half, cumulative, median = fsum(weights) / 2, 0.0, None
    for index, (target, weight) in enumerate(pairs):
        cumulative += weight
        if cumulative >= half:
            median = (
                (target + pairs[index + 1][0]) / 2
                if abs(cumulative - half) < 1e-12 and index + 1 < len(pairs)
                else target
            )
            break
    return {"mean": mean, "median": median}


def train(bundle):
    if (
        set(bundle)
        != {"schema", "origin", "cohort_id", "protocol", "timing", "rows", "membership_digest"}
        or bundle["schema"] != "package-history-training-export/1"
        or bundle["origin"] not in {"synthetic", "external_evidence"}
    ):
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_EXPORT_INVALID", "Only the purpose-bound SQL export is accepted"
        )
    frozen_protocol = bundle["protocol"]
    protocol_digest = validate_protocol(frozen_protocol)
    rows = _rows(bundle["rows"])
    timing = bundle["timing"]
    boundary, cutoff, frozen = (
        instant(timing[k])
        for k in ("submission_split_at", "label_available_as_of", "training_frozen_at")
    )
    if cutoff > frozen or boundary > frozen:
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_TIMING_INVALID",
            "Separate historical split and actual label cutoff required",
        )
    groups: dict[str, str] = {}
    for row in rows:
        if (
            instant(row["submitted_at"]) >= boundary
            or not instant(row["submitted_at"]) <= instant(row["label_known_at"]) <= cutoff
        ):
            raise GovernanceError(
                "PACKAGE_HISTORY_CPU_TIMING_INVALID",
                "Retrospective training rows cross their frozen boundary",
            )
        if groups.setdefault(row["group_id"], row["purpose"]) != row["purpose"]:
            raise GovernanceError(
                "PACKAGE_HISTORY_CPU_GROUP_LEAK", "Connected groups cannot cross fitting purposes"
            )
    fit = [r for r in rows if r["purpose"] == "fit"]
    development = [r for r in rows if r["purpose"] == "development"]
    calibration = [r for r in rows if r["purpose"] == "calibration"]
    if len({r["group_id"] for r in fit}) < 2 or not development:
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_INDEPENDENT_GROUPS_REQUIRED",
            "Two fitting groups and independent development are required",
        )
    constants = _constants(fit)
    losses = {
        name: evaluation.project_mean(
            [dict(row, loss=abs(finite(row["target"]) - value)) for row in development], "loss"
        )
        for name, value in constants.items()
    }
    selected = min(
        constants, key=lambda name: (losses[name], frozen_protocol["tie_order"].index(name))
    )
    model = wire(
        {
            "schema": "package-history-constant-model/1",
            "method_digest": frozen_protocol["method"]["digest"],
            "family": selected,
            "constant": constants[selected],
            "training_export_digest": digest(bundle),
        }
    )
    residuals = defaultdict(list)
    for row in calibration:
        residuals[row["group_id"]].append(abs(finite(row["target"]) - constants[selected]))
    maxima = sorted(max(v) for v in residuals.values())
    intervals = {}
    for level in frozen_protocol["interval_levels"]:
        rank = ceil((len(maxima) + 1) * level)
        intervals[str(level)] = {
            "radius": maxima[rank - 1] if maxima and rank <= len(maxima) else None,
            "groups": len(maxima),
            "rank": rank,
            "unavailable_reason": None
            if maxima and rank <= len(maxima)
            else "insufficient_independent_calibration_groups",
        }
    return wire(
        {
            "schema": "package-history-training-result/1",
            "origin": bundle["origin"],
            "cohort_id": bundle["cohort_id"],
            "protocol_digest": protocol_digest,
            "training_export_digest": digest(bundle),
            "membership_digest": bundle["membership_digest"],
            "model": model,
            "model_digest": digest(model),
            "baselines": constants,
            "selection": {
                "development_project_mae": losses,
                "selected": selected,
                "refit_with_development": False,
            },
            "intervals": intervals,
            "research_only": True,
            "formal_eligibility": "unavailable",
            "provider_requests": 0,
            "paid_calls": 0,
        }
    )


def evaluate(bundle):
    if (
        set(bundle)
        != {
            "schema",
            "origin",
            "cohort_id",
            "protocol",
            "timing",
            "labels",
            "labels_digest",
            "predictions",
            "predictions_digest",
            "model_digest",
            "membership_digest",
            "denominator",
        }
        or bundle["schema"] != "package-history-final-evaluation-export/1"
    ):
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_EXPORT_INVALID",
            "Committed exposure and purpose-bound final export required",
        )
    frozen_protocol = bundle["protocol"]
    protocol_digest = validate_protocol(frozen_protocol)
    labels, predictions = bundle["labels"], bundle["predictions"]
    if (
        digest(labels) != bundle["labels_digest"]
        or digest(predictions) != bundle["predictions_digest"]
    ):
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_SEAL_CHANGED",
            "Final labels and predictions must remain exactly frozen",
        )
    by_id = {r["id"]: r for r in predictions["rows"]}
    if (
        len(by_id) != len(predictions["rows"])
        or len(labels) != len({r["id"] for r in labels})
        or set(by_id) != {r["id"] for r in labels}
    ):
        raise GovernanceError(
            "PACKAGE_HISTORY_CPU_DENOMINATOR_CHANGED",
            "Every frozen final-side candidate must be reported",
        )
    rows = []
    for row in labels:
        predicted = by_id[row["id"]]
        if row["status"] != predicted["status"]:
            raise GovernanceError(
                "PACKAGE_HISTORY_CPU_DENOMINATOR_CHANGED",
                "Failures and exclusions cannot become successes",
            )
        numeric = {**row, "prediction": predicted["prediction"]}
        if row["status"] == "succeeded":
            # Only the in-memory computation copy changes representation. The
            # exact SQL export and its decimal-string digests remain unchanged.
            numeric.update(
                target=finite(row["target"], lower=0, upper=100),
                prediction=finite(predicted["prediction"], lower=0, upper=100),
                maximum=finite(row["maximum"], lower=1e-9, upper=1e9),
            )
        rows.append(numeric)
    report = evaluation.metrics(
        rows,
        expected_ids=sorted(by_id),
        intervals=predictions["intervals"],
        seed=frozen_protocol["seed"],
        bootstrap_iterations=frozen_protocol["bootstrap_iterations"],
        baseline_predictions=predictions["baseline_predictions"],
    )
    return wire(
        {
            "schema": "package-history-independent-evaluation/1",
            "origin": bundle["origin"],
            "cohort_id": bundle["cohort_id"],
            "protocol_digest": protocol_digest,
            "model_digest": bundle["model_digest"],
            "membership_digest": bundle["membership_digest"],
            "predictions_digest": bundle["predictions_digest"],
            "labels_digest": bundle["labels_digest"],
            "timing": bundle["timing"],
            "selection_denominator": bundle["denominator"],
            "report": report,
            "official_source_subset": {
                "scope": "verified_official_associations_with_evidence_backed_admission",
                "origin": bundle["origin"],
                "report": report,
            },
            "research_only": True,
            "formal_eligibility": "unavailable",
            "acceptance_decision": "unavailable",
            "missing_acceptance": [
                "real_independent_quality_validation",
                "complete_package_three_judgment_features",
                "preexposure_business_certification",
                "independent_repeat_stability",
                "observation_and_release_authority",
            ],
            "provider_requests": 0,
            "paid_calls": 0,
        }
    )
