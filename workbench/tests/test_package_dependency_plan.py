"""Synthetic archival plans preserve original policy and select no unused fact values."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_input_dependencies import case, declaration, run, uid

from packages.domain import package_dependency_plan as plans
from packages.domain import package_input_dependencies as dependencies
from packages.domain.review_identity import digest


def make(case):
    assessment, usage, _ = run(case, [declaration(case)])
    body = {
        "execution_input_digest": case["prepared"].digest,
        "purpose": "prebid_compliance",
        "fact_ids": [uid(10)],
        "dependencies": [declaration(case)],
        "assessment_digest": assessment.digest,
        "reason": "明确保存本轮人工核对计划",
    }
    value = plans.build(
        case["frozen"],
        case["prepared"],
        usage,
        assessment,
        record_id=uid(90),
        actor_id=uid(91),
        command_id=uid(92),
        saved_at="2026-10-20T08:00:00.000000Z",
        body=body,
    )
    return value, body, usage, assessment


def test_owned_plan_receipt_omits_fact_values_and_never_qualifies(case):
    plan, body, _, _ = make(case)
    original = plan.view()
    body["dependencies"].clear()
    changed = plan.view()
    changed["manifest"]["assessment"]["manifest"]["requirements"].clear()
    assert plan.view() == original
    assert "value_jsonb_text" not in repr(original)
    assert "value" not in original["manifest"]["usage"]["manifest"]
    assert (
        original["manifest"]["assessment"]["manifest"]["required_facts_assessment"]
        == "selected_unvalidated"
    )
    assert original["manifest"]["launch_available"] is False
    assert plans.read(original, case["frozen"], case["prepared"]).view() == original


def test_history_does_not_recompute_against_current_dependency_policy(case, monkeypatch):
    value, _, _, _ = make(case)
    monkeypatch.setattr(
        dependencies, "assess", lambda *args: pytest.fail("history must not re-assess")
    )
    assert plans.read(value.view(), case["frozen"], case["prepared"]).view() == value.view()


@pytest.mark.parametrize(
    "field",
    [
        "execution_input_digest",
        "assessment_digest",
        "fact_ids",
        "dependencies",
        "purpose",
        "reason",
    ],
)
def test_new_plan_requires_exact_checked_selection_and_explicit_reason(case, field):
    _, body, usage, assessment = make(case)
    body[field] = [] if field in {"fact_ids", "dependencies"} else "a" * 64
    if field == "reason":
        body[field] = " "
    with pytest.raises(ValueError):
        plans.build(
            case["frozen"],
            case["prepared"],
            usage,
            assessment,
            record_id=uid(90),
            actor_id=uid(91),
            command_id=uid(92),
            saved_at="2026-10-20T08:00:00Z",
            body=body,
        )


@pytest.mark.parametrize(
    "field",
    [
        "digest",
        "assessment_digest",
        "usage_digest",
        "frozen_digest",
        "prepared",
        "facts_qualified",
        "review_ready",
        "inventory_complete",
    ],
)
def test_changed_or_resealed_original_bindings_never_read_as_saved_plan(case, field):
    plan, _, _, _ = make(case)
    bad = deepcopy(plan.view())
    m = bad["manifest"]
    if field == "digest":
        bad["digest"] = "a" * 64
    elif field in {"facts_qualified", "review_ready", "inventory_complete"}:
        m[field] = True
    elif field == "prepared":
        m["prepared"]["execution_input_id"] = uid(99)
    elif field == "assessment_digest":
        m["assessment"]["digest"] = "a" * 64
    elif field == "usage_digest":
        m["usage"]["digest"] = "a" * 64
    else:
        m["assessment"]["manifest"]["frozen_digest"] = "a" * 64
        m["assessment"]["digest"] = digest(m["assessment"]["manifest"])
    if field != "digest":
        bad["digest"] = digest(m)
    with pytest.raises(ValueError):
        plans.read(bad, case["frozen"], case["prepared"])
