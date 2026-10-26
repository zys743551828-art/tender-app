"""Versioned six-feature research candidate; old baseline methods stay untouched.

Projection never accepts labels. Fit-only project-weighted transforms and ridge
solve reuse the existing statistical primitives; no paid calls or native grants.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from math import ceil, fsum, sqrt
from pathlib import Path

from packages.domain.review_identity import digest
from packages.model_governance import evaluation, statistics
from packages.model_governance import package_complete_features as aggregate
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_handoff as local
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import GovernanceError, finite
from packages.storage.private_cas import sha

VERSION = "package-complete-feature-training/1"
SCHEMA = "package-complete-numeric-features/1"
MODEL = "package-complete-ridge-model/1"
FEATURES = [
    "declared_band_fraction",
    "modal_agreement",
    "specificity_supported",
    "validity_supported",
    "consistency_supported",
    "uncertain_fraction",
]
ALPHAS = ["10", "1", "0.1"]
MIN_GROUPS = {"fit": 3, "development": 2, "calibration": 9}


class ProjectionUnavailable(ValueError):
    pass


def fail(code):
    raise GovernanceError("PACKAGE_FEATURE_TRAINING_" + code, "Frozen feature research rejected")


def method():
    value = {
        "version": VERSION,
        "feature_schema": SCHEMA,
        "feature_names": list(FEATURES),
        "source_digest": sha(Path(__file__).read_bytes()),
        "consumer_source": sha(
            Path(__file__).with_name("package_feature_training_io.py").read_bytes()
        ),
        "handoff_method": handoff.method_digest(),
        "cpu_method": cpu.method(),
        "alphas_and_tie_order": list(ALPHAS),
        "minimum_independent_groups": dict(MIN_GROUPS),
        "interval_levels": ["0.8", "0.9"],
        "transform_fit": "fit_projects_only",
        "selection": "development_project_mae",
        "refit_with_development": False,
        "final_test_consumption": "not_implemented",
    }
    return value | {"digest": digest(value)}


def project(loaded):
    """Only fully revalidated /3 material, never an outcome or label argument."""
    loaded = deepcopy(loaded)
    bundle = loaded.bundle
    summaries = handoff._summaries(
        bundle, loaded.attempts, bundle.metadata["digest"], aggregate.method_digest()
    )
    if summaries != loaded.features:
        fail("FEATURES_CHANGED")
    rules = {
        r["rule_id"]: r for r in bundle.context.metadata["rules"] if r["selection"] == "include"
    }
    weighted, total = [], 0.0
    for summary in summaries:
        rule = rules[summary["rule_id"]]
        try:
            maximum = finite(
                rule["frozen_rule"]["rule_snapshot"]["max_points"], lower=1e-9, upper=1e9
            )
            points = {
                b["band_id"]: finite(b["source"]["points"], lower=0, upper=maximum)
                for b in rule["bands"]
            }
        except (GovernanceError, KeyError, TypeError):
            raise ProjectionUnavailable("declared_numeric_band_scale_required") from None
        if len(points) < 2 or len(set(points.values())) < 2:
            raise ProjectionUnavailable("distinct_declared_numeric_bands_required")
        votes = summary["features"]
        bands = votes["band_votes"]
        dimensions = votes["dimension_votes"]
        if sum(b["count"] for b in bands) != 3:
            fail("INCOMPLETE_VOTES")
        vector = [
            fsum(points[b["band_id"]] * b["count"] for b in bands) / (3 * maximum),
            max(b["count"] for b in bands) / 3,
        ]
        vector += [
            dimensions[k]["supported"] / 3 for k in ("specificity", "validity", "consistency")
        ]
        vector += [sum(dimensions[k]["uncertain"] for k in dimensions) / 9]
        weighted.append((maximum, vector))
        total += maximum
    if not weighted:
        raise ProjectionUnavailable("included_rules_required")
    total = fsum(w for w, _ in weighted)
    values = [fsum(w * v[j] for w, v in weighted) / total for j in range(len(FEATURES))]
    value = {
        "schema": SCHEMA,
        "method_digest": method()["digest"],
        "input_digest": bundle.metadata["digest"],
        "features_digest": digest(summaries),
        "values": cpu.wire(values),
    }
    return value | {"digest": digest(value)}


def vector(value):
    if type(value) is not list or len(value) != len(FEATURES):
        fail("VECTOR_SCHEMA")
    return [finite(v, lower=0, upper=1) for v in value]


def predict(model, values):
    if (
        set(model)
        != {
            "version",
            "feature_schema",
            "method_digest",
            "alpha",
            "means",
            "scales",
            "coefficients",
            "intercept",
            "training_digest",
        }
        or model["version"] != MODEL
        or model["feature_schema"] != SCHEMA
        or model["method_digest"] != method()["digest"]
        or model["alpha"] not in ALPHAS
    ):
        fail("MODEL_SCHEMA")
    for key in ("means", "scales", "coefficients"):
        if type(model[key]) is not list or len(model[key]) != len(FEATURES):
            fail("MODEL_SCHEMA")
    means = vector(model["means"])
    scales = [finite(v, lower=1e-12, upper=1) for v in model["scales"]]
    coefficients = [finite(v) for v in model["coefficients"]]
    predicted = finite(model["intercept"], lower=0, upper=100) + fsum(
        coefficient * (x - mean) / scale
        for coefficient, x, mean, scale in zip(
            coefficients, vector(values), means, scales, strict=True
        )
    )
    return min(100.0, max(0.0, finite(predicted)))


def _fit(rows, alpha):
    counts = Counter(r["project_id"] for r in rows)
    weights = [1 / counts[r["project_id"]] for r in rows]
    xs = [vector(r["features"]) for r in rows]
    ys = [finite(r["target"], lower=0, upper=100) for r in rows]
    mean_y = statistics.weighted_mean(ys, weights)
    means = [statistics.weighted_mean([x[j] for x in xs], weights) for j in range(len(FEATURES))]
    variance = [
        statistics.weighted_mean([(x[j] - means[j]) ** 2 for x in xs], weights)
        for j in range(len(FEATURES))
    ]
    if max(variance) <= 1e-12:
        raise ProjectionUnavailable("fit_features_have_no_variation")
    # Near-constant columns remain unscaled; this choice uses fit only.
    scales = [sqrt(v) if v > 1e-12 else 1.0 for v in variance]
    x = [[(v - m) / s for v, m, s in zip(row, means, scales, strict=True)] for row in xs]
    matrix = [
        [
            fsum(w * row[i] * row[j] for row, w in zip(x, weights, strict=True))
            + (float(alpha) if i == j else 0)
            for j in range(len(FEATURES))
        ]
        for i in range(len(FEATURES))
    ]
    rhs = [
        fsum(w * row[i] * (y - mean_y) for row, y, w in zip(x, ys, weights, strict=True))
        for i in range(len(FEATURES))
    ]
    return cpu.wire(
        {
            "version": MODEL,
            "feature_schema": SCHEMA,
            "method_digest": method()["digest"],
            "alpha": alpha,
            "means": means,
            "scales": scales,
            "coefficients": statistics.solve(matrix, rhs),
            "intercept": mean_y,
            "training_digest": digest(rows),
        }
    )


def train(bundle, projections, *, expected_method_digest, source_digest):
    local.checksum(source_digest)
    if (
        type(bundle) is not dict
        or type(bundle.get("rows")) is not list
        or not 1 <= len(bundle["rows"]) <= 64
        or type(projections) is not dict
        or len(projections) > 64
    ):
        fail("ROW_LIMIT")
    bundle, projections = deepcopy(bundle), deepcopy(projections)
    if expected_method_digest != method()["digest"]:
        fail("METHOD_CHANGED")
    # Reuse the frozen baseline validator (including times and purpose groups).
    # Its output never enters feature fitting or candidate selection.
    cpu.train(bundle)
    rows = bundle["rows"]
    if len(rows) > 64 or set(projections) != {r["id"] for r in rows}:
        fail("DENOMINATOR_CHANGED")
    partitions: dict[tuple[str, str], str] = {}
    project_groups: dict[str, str] = {}
    own = []
    seen_inputs = set()
    reasons = []
    for row in rows:
        if project_groups.setdefault(row["project_id"], row["group_id"]) != row["group_id"]:
            fail("PROJECT_GROUP_CHANGED")
        for key in ("project_id", "group_id"):
            identity = (key, row[key])
            if partitions.setdefault(identity, row["purpose"]) != row["purpose"]:
                fail("PARTITION_LEAK")
        projection = projections[row["id"]]
        if isinstance(projection, str):
            if projection not in {
                "declared_numeric_band_scale_required",
                "distinct_declared_numeric_bands_required",
                "included_rules_required",
            }:
                fail("PROJECTION_STATUS")
            reasons.append(projection)
            continue
        if (
            set(projection)
            != {"schema", "method_digest", "input_digest", "features_digest", "values", "digest"}
            or projection["schema"] != SCHEMA
            or projection["method_digest"] != expected_method_digest
            or digest({k: v for k, v in projection.items() if k != "digest"})
            != projection["digest"]
        ):
            fail("PROJECTION_CHANGED")
        for key in ("input_digest", "features_digest"):
            local.checksum(projection[key])
        if projection["input_digest"] in seen_inputs:
            fail("INPUT_REUSED")
        seen_inputs.add(projection["input_digest"])
        vector(projection["values"])
        own.append(dict(row, features=list(projection["values"])))
    groups = {p: len({r["group_id"] for r in rows if r["purpose"] == p}) for p in MIN_GROUPS}
    reasons += [f"insufficient_{p}_groups" for p in MIN_GROUPS if groups[p] < MIN_GROUPS[p]]
    result = {
        "version": VERSION,
        "method_digest": expected_method_digest,
        "feature_schema": SCHEMA,
        "feature_names": list(FEATURES),
        "origin": bundle["origin"],
        "membership_digest": bundle["membership_digest"],
        "projection_digest": digest(projections),
        "source_digest": source_digest,
        "status": "unavailable",
        "unavailable_reasons": sorted(set(reasons)),
        "groups": groups,
        "model": None,
        "model_digest": None,
        "selection": None,
        "intervals": None,
        "features_used_for_fit": False,
        "formal_prediction": None,
        "final_test_consumption": "not_implemented",
        **handoff.FLAGS,
    }
    if reasons:
        return result
    fit = [r for r in own if r["purpose"] == "fit"]
    development = [r for r in own if r["purpose"] == "development"]
    calibration = [r for r in own if r["purpose"] == "calibration"]
    try:
        candidates = {alpha: _fit(fit, alpha) for alpha in ALPHAS}
    except ProjectionUnavailable as error:
        return result | {"unavailable_reasons": [str(error)]}
    losses = {
        alpha: evaluation.project_mean(
            [
                dict(r, loss=abs(finite(r["target"]) - predict(model, r["features"])))
                for r in development
            ],
            "loss",
        )
        for alpha, model in candidates.items()
    }
    chosen = min(ALPHAS, key=lambda a: (losses[a], ALPHAS.index(a)))
    model = candidates[chosen]
    residuals = defaultdict(list)
    for row in calibration:
        residuals[row["group_id"]].append(
            abs(finite(row["target"]) - predict(model, row["features"]))
        )
    maxima = sorted(max(v) for v in residuals.values())
    intervals = {
        str(level): {
            "radius": maxima[ceil((len(maxima) + 1) * level) - 1],
            "groups": len(maxima),
            "rank": ceil((len(maxima) + 1) * level),
        }
        for level in (0.8, 0.9)
    }
    return cpu.wire(
        result
        | {
            "status": "research_candidate",
            "model": model,
            "model_digest": digest(model),
            "selection": {
                "selected_alpha": chosen,
                "development_project_mae": losses,
                "refit_with_development": False,
            },
            "intervals": intervals,
            "features_used_for_fit": True,
        }
    )
