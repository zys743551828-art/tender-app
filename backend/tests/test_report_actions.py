"""报告的“下一步”：按对中标的影响排序，且“无法判断”不会被当作“满足”。"""

from __future__ import annotations

from bidwb.schemas import CategoryCount, Compliance, PipelineStatus, ProjectSettings, VerdictCounts
from bidwb.services.report import _next_actions


def _counts(**kw: int) -> VerdictCounts:
    base = {"total": 0, "satisfied": 0, "violated": 0, "unclear": 0, "failed": 0}
    return VerdictCounts(**{**base, **kw})


def _matrix(**qualification: int) -> Compliance:
    return Compliance(
        snapshot_id="snp_1", run_id="job_1", coverage=None, qualification=_counts(**qualification), scoring=_counts(), rows=[]
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


def _keys(**kw) -> list[str]:  # type: ignore[no-untyped-def]
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
    return [a.key for a in _next_actions(**{**defaults, **kw})]


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
    assert keys == ["handle_disqualification", "review_unclear", "confirm_rules", "handle_findings", "set_price"]


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
    assert _keys(**busy) == ["confirm_rules", "set_price", "record_outcome"]
    quiet = ProjectSettings(price=False, outcome_tracking=False, accept_rules_as_written=True)
    assert _keys(**busy, settings=quiet) == []


def test_manual_start_is_offered_when_inputs_changed() -> None:
    assert _keys(status_=_status("waiting_start", stale=["body_updated"]), project_state="issues_open")[0] == "start_analysis"
