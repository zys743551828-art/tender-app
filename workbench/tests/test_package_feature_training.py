"""Synthetic ridge mechanisms, not evidence of predictive quality."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import GovernanceError


def data():
    rows, projections = [], {}
    for i, purpose in enumerate(["fit"] * 4 + ["development"] * 2 + ["calibration"] * 9):
        identity = str(uuid4())
        x = (i % 4) / 3
        rows.append(
            {
                "id": identity,
                "project_id": str(uuid4()),
                "group_id": str(uuid4()),
                "purpose": purpose,
                "submitted_at": "2026-01-01T00:00:00Z",
                "label_known_at": "2026-02-01T00:00:00Z",
                "target": str(20 + 60 * x),
            }
        )
        p = {
            "schema": training.SCHEMA,
            "method_digest": training.method()["digest"],
            "input_digest": digest(["synthetic-input", i]),
            "features_digest": digest(["votes", i]),
            "values": cpu.wire([x, 1, x, 1 - x, 0.5, 0.2]),
        }
        projections[identity] = p | {"digest": digest(p)}
    bundle = {
        "schema": "package-history-training-export/1",
        "origin": "synthetic",
        "cohort_id": str(uuid4()),
        "membership_digest": "a" * 64,
        "protocol": cpu.protocol(),
        "rows": rows,
        "timing": {
            "submission_split_at": "2026-03-01T00:00:00Z",
            "label_available_as_of": "2026-02-02T00:00:00Z",
            "training_frozen_at": "2026-03-02T00:00:00Z",
        },
    }
    return bundle, projections


def fit(bundle, projections):
    return training.train(
        bundle,
        projections,
        expected_method_digest=training.method()["digest"],
        source_digest="b" * 64,
    )


def test_feature_model_uses_inputs_and_has_fit_only_transform():
    bundle, projections = data()
    result = fit(bundle, projections)
    assert result["status"] == "research_candidate" and result["features_used_for_fit"]
    assert result["model"]["means"][0] == "0.5"
    assert training.predict(result["model"], [0, 1, 0, 1, 0.5, 0.2]) < training.predict(
        result["model"], [1, 1, 1, 0, 0.5, 0.2]
    )
    assert result["intervals"]["0.9"]["groups"] == 9
    assert not result["training_eligible"] and result["formal_prediction"] is None
    assert result["final_test_consumption"] == "not_implemented"


def test_calibration_labels_and_features_cannot_change_fit_or_selection():
    bundle, projections = data()
    first = fit(bundle, projections)
    for row in bundle["rows"]:
        if row["purpose"] == "calibration":
            row["target"] = "0"
            p = projections[row["id"]]
            p["values"] = ["0"] * 6
            p["digest"] = digest({k: v for k, v in p.items() if k != "digest"})
    second = fit(bundle, projections)
    assert first["model"] == second["model"]
    assert first["selection"] == second["selection"]
    assert first["intervals"] != second["intervals"]


def test_development_only_selects_frozen_fit_candidates():
    bundle, projections = data()
    for row in bundle["rows"]:
        if row["purpose"] == "development":
            row["target"] = "100"
    result = fit(bundle, projections)
    selected = result["selection"]["selected_alpha"]
    fit_rows = [
        dict(r, features=projections[r["id"]]["values"])
        for r in bundle["rows"]
        if r["purpose"] == "fit"
    ]
    assert result["model"] == training._fit(fit_rows, selected)
    assert result["selection"]["refit_with_development"] is False


@pytest.mark.parametrize(
    "attack",
    ["project", "group", "final", "duplicate_input", "method", "vector", "missing", "future_label"],
)
def test_rejects_leaks_and_changed_inputs(attack):
    bundle, projections = data()
    if attack in {"project", "group"}:
        bundle["rows"][4][attack + "_id"] = bundle["rows"][0][attack + "_id"]
    elif attack == "final":
        bundle["rows"][-1]["purpose"] = "final"
    elif attack == "duplicate_input":
        second = projections[bundle["rows"][1]["id"]]
        second["input_digest"] = projections[bundle["rows"][0]["id"]]["input_digest"]
        second["digest"] = digest({k: v for k, v in second.items() if k != "digest"})
    elif attack == "method":
        projections[bundle["rows"][0]["id"]]["method_digest"] = "f" * 64
    elif attack == "vector":
        projections[bundle["rows"][0]["id"]]["values"] = ["1"]
    elif attack == "missing":
        projections.pop(bundle["rows"][0]["id"])
    elif attack == "future_label":
        bundle["rows"][0]["label_known_at"] = "2027-01-01T00:00:00Z"
    with pytest.raises(GovernanceError):
        fit(bundle, projections)


@pytest.mark.parametrize("purpose", ["fit", "development", "calibration"])
def test_insufficient_groups_produce_no_model_or_intervals(purpose):
    bundle, projections = data()
    drop = next(r for r in bundle["rows"] if r["purpose"] == purpose)
    if purpose == "fit":
        # Four initial fitting groups, remove two; the old baseline still accepts two.
        other = next(r for r in bundle["rows"] if r["purpose"] == purpose and r != drop)
        bundle["rows"].remove(other)
        projections.pop(other["id"])
    bundle["rows"].remove(drop)
    projections.pop(drop["id"])
    result = fit(bundle, projections)
    assert result["status"] == "unavailable" and result["model"] is None
    assert result["intervals"] is None and not result["features_used_for_fit"]


def test_zero_variance_and_unsupported_projection_fail_closed():
    bundle, projections = data()
    for projection in projections.values():
        projection["values"] = ["0"] * 6
        projection["digest"] = digest({k: v for k, v in projection.items() if k != "digest"})
    assert fit(bundle, projections)["unavailable_reasons"] == ["fit_features_have_no_variation"]
    projections[bundle["rows"][0]["id"]] = "declared_numeric_band_scale_required"
    result = fit(bundle, projections)
    assert result["status"] == "unavailable" and result["model"] is None


def test_reordering_calibration_does_not_select_again():
    bundle, projections = data()
    first = fit(bundle, projections)
    changed = deepcopy(bundle)
    changed["rows"] = changed["rows"][:6] + list(reversed(changed["rows"][6:]))
    second = fit(changed, projections)
    assert first["model"] == second["model"] and first["selection"] == second["selection"]
    assert first["intervals"] == second["intervals"]


def test_one_project_cannot_invent_independent_groups():
    bundle, projections = data()
    bundle["rows"][1]["project_id"] = bundle["rows"][0]["project_id"]
    with pytest.raises(GovernanceError, match="Frozen feature research rejected"):
        fit(bundle, projections)


def test_descriptor_does_not_expose_mutable_global_protocol():
    before = training.method()
    changed = training.method()
    changed["feature_names"].append("official_label")
    changed["alphas_and_tie_order"].append("0")
    changed["minimum_independent_groups"]["fit"] = 1
    assert training.method() == before
