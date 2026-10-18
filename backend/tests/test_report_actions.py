"""报告的“下一步”：按对中标的影响排序，且“无法判断”不会被当作“满足”。"""

from __future__ import annotations

from bidwb.schemas import CategoryCount, Compliance, PipelineStatus, ProjectSettings, TaskCoverage, VerdictCounts
from bidwb.services.report import _next_actions


def _counts(**kw: int) -> VerdictCounts:
    base = {"total": 0, "satisfied": 0, "violated": 0, "unclear": 0, "failed": 0}
    return VerdictCounts(**{**base, **kw})


def _matrix(**qualification: int) -> Compliance:
    return Compliance(
        snapshot_id="snp_1",
        run_id="job_1",
        coverage=TaskCoverage(status="complete", rules_total=2, rules_checked=2, rules_failed=0, candidates_dropped=0),
        qualification=_counts(**qualification),
        scoring=_counts(),
        rows=[],
    )


def _categories(**open_: int) -> list[CategoryCount]:
    names = ("disqualification", "response", "consistency", "scope", "improvement")
    return [CategoryCount(category=n, total=open_.get(n, 0), open=open_.get(n, 0), resolved=0) for n in names]  # type: ignore[arg-type]


def _status(stage: str = "done", stale: list[str] | None = None) -> PipelineStatus:
    return PipelineStatus(
        project_id="prj_1",
        stage=stage,  # type: ignore[arg-type]
        steps=[],
        missing=[],
        snapshot_id="snp_1",
        round_no=1,
        stale_reasons=stale or [],  # type: ignore[arg-type]
        rules_total=3,
        rules_unconfirmed=0,
    )


def _actions(**kw):  # type: ignore[no-untyped-def]
    defaults = {
        "status_": _status(),
        "matrix": _matrix(total=2, satisfied=2),
        "categories": _categories(),
        "unconfirmed_qualification": 0,
        "has_price": True,
        "submitted": False,
        "has_outcome": False,
        "project_state": "ready_to_submit",
        "settings": ProjectSettings(),
    }
    return _next_actions(**{**defaults, **kw})


def _keys(**kw) -> list[str]:  # type: ignore[no-untyped-def]
    return [a.key for a in _actions(**kw)]


def test_six_levels_and_counts_come_from_current_business_groups() -> None:
    actions = _actions(
        categories=_categories(disqualification=1, consistency=4, improvement=2),
        critical_open=1,
        facts_open=1,
        technical_open=2,
        suggestions_open=2,
        scoring_gap=True,
        unconfirmed_qualification=1,
        has_price=False,
        project_state="issues_open",
    )
    assert [a.key for a in actions] == [
        "handle_disqualification",
        "handle_critical",
        "confirm_rules",
        "verify_facts",
        "handle_findings",
        "improve_score",
        "handle_suggestions",
        "set_price",
    ]
    assert [a.priority for a in actions] == [3, 3, 4, 4, 5, 5, 6, 6]
    assert next(a for a in actions if a.key == "handle_findings").count == 2


def test_changed_input_hides_historical_risk_actions() -> None:
    assert _keys(status_=_status(stale=["body_updated"]), categories=_categories(disqualification=3)) == ["reanalyze"]
    assert _keys(status_=_status("running"), categories=_categories(disqualification=3)) == ["wait_analysis"]
    assert _keys(
        status_=_status().model_copy(update={"input_verification_required": True}), categories=_categories(disqualification=3)
    ) == ["verify_sources"]


def test_incomplete_coverage_precedes_risks_and_cannot_offer_submission() -> None:
    matrix = _matrix(total=2, satisfied=1, failed=1)
    matrix.coverage = TaskCoverage(status="partial", rules_total=2, rules_checked=1, rules_failed=1, candidates_dropped=0)
    actions = _actions(matrix=matrix, categories=_categories(disqualification=1))
    assert actions[0].key == "retry_analysis" and actions[0].priority == 2
    assert "submit" not in [a.key for a in actions]


def test_eligible_submission_precedes_optional_suggestions_and_price() -> None:
    assert _keys(categories=_categories(improvement=2), has_price=False) == ["submit", "handle_suggestions", "set_price"]


def test_clean_review_goes_straight_to_submission() -> None:
    assert _keys() == ["submit"]


def test_qualification_risks_come_first_then_unclear_then_rules_then_score_issues() -> None:
    keys = _keys(
        matrix=_matrix(total=4, satisfied=1, violated=1, unclear=2),
        categories=_categories(disqualification=1, improvement=2),
        unconfirmed_qualification=2,
        has_price=False,
        project_state="issues_open",
    )
    assert keys == ["handle_disqualification", "review_unclear", "confirm_rules", "handle_suggestions", "set_price"]


def test_failed_check_is_surfaced_like_unclear() -> None:
    assert "review_unclear" in _keys(matrix=_matrix(total=2, satisfied=1, failed=1), project_state="issues_open")


def test_pipeline_state_and_outcome_prompts() -> None:
    assert _keys(status_=_status("failed"), project_state="analysis_failed")[0] == "retry_analysis"
    assert _keys(status_=_status("running"), project_state="analyzing")[0] == "wait_analysis"
    assert "reanalyze" in _keys(status_=_status(stale=["rules_changed"]))
    assert _keys(submitted=True, project_state="submitted") == ["record_outcome"]
    assert _keys(submitted=True, has_outcome=True, project_state="submitted") == []


def test_switched_off_modules_do_not_ask_for_anything() -> None:
    busy = {"has_price": False, "submitted": True, "unconfirmed_qualification": 2, "project_state": "submitted"}
    assert _keys(**busy) == ["confirm_rules", "record_outcome", "set_price"]
    quiet = ProjectSettings(price=False, outcome_tracking=False, accept_rules_as_written=True)
    assert _keys(**busy, settings=quiet) == []


def test_manual_start_is_offered_when_inputs_changed() -> None:
    assert _keys(status_=_status("waiting_start", stale=["body_updated"]), project_state="issues_open")[0] == "start_analysis"
