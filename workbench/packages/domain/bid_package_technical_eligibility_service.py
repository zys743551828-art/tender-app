"""Read/lock adapters for exact-package technical scoring and sample contexts.

No commands, scores, samples or model jobs are written here. Registry lookups
are explicit, never latest-by-default. Base-only deployments return unavailable
denominators without trying optional authority tables.
"""

from packages.domain import bid_package_submission_repository as submissions
from packages.domain import bid_package_technical_scope_repository as scopes
from packages.domain import package_technical_eligibility as policy
from packages.domain.bid_package_service import lock_bid
from packages.domain.runtime import DomainError, clean, etag, require_read_committed, sha
from packages.knowledge.sources import lock_graph
from packages.model_governance import scale_repository as scales
from packages.research import outcomes, package_outcomes


def _lock(c, scope):
    # Same governance -> bid -> source lock order as the denominator authority.
    # READ COMMITTED prevents waiting on a lock then reading an older snapshot.
    require_read_committed(c)
    c.execute("SELECT pg_advisory_xact_lock(91143,1)")
    lock_bid(c, scope[0])
    lock_graph(c)
    scopes.require_schema(c)


def _observe(c, scope, saved):
    try:
        return scopes.observe(
            c, scope, saved["manifest"]["preview"]["manifest"]["scope"]["inventory_id"]
        )["snapshot"], None
    except DomainError as error:
        # A missing/corrupt *current* dependency does not erase the original scope.
        # Transport/SQL failures are not swallowed as business eligibility gaps.
        return None, error.code


def _denominator(c, scope, saved, snapshot, scale_id, *, purpose, submission_id=None):
    if scale_id is None:
        return policy.missing_scale(purpose)
    if not scales.configured(c):
        return policy.missing_scale(purpose, scale_id, configured=False)
    # Scope the exact registry row before asking its API to read any evidence.
    row = c.execute(
        "SELECT id FROM technical_scale.versions WHERE bid_id=%s AND id=%s",
        (scope[0], scale_id),
    ).fetchone()
    if row is None:
        raise DomainError("PACKAGE_TECHNICAL_SCALE_NOT_FOUND", "本项目没有所选确切满分权威", 404)
    if snapshot is None:
        return policy.missing_scale(purpose, scale_id, unavailable=True)
    try:
        value, _ = scales.view(c, scale_id)
    except DomainError as error:
        result = policy.missing_scale(purpose, scale_id, unavailable=True)
        result["reasons"].append(
            policy.reason(error.code, "所选独立满分权威未能通过当前来源与用途核验。", scale_id)
        )
        return result
    return policy.scale_assessment(
        saved, snapshot, value, purpose=purpose, submission_id=submission_id
    )


def _time(c):
    return c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat()


def scoring_context(c, scope, scope_id, scale_id=None):
    scope = tuple(map(str, scope))
    _lock(c, scope)
    saved = scopes.load(c, scope, str(scope_id))
    snapshot, error = _observe(c, scope, saved)
    maximum = _denominator(
        c, scope, saved, snapshot, str(scale_id) if scale_id else None, purpose="current_prebid"
    )
    value = policy.scoring_context(
        saved, snapshot, maximum, observed_at=_time(c), observation_error=error
    )
    return value, _etag(value)


def _official(c, bid, submission, outcome_id):
    result = {
        "outcome_id": outcome_id,
        "score_kind": None,
        "technical_value": None,
        "reported_maximum": None,
        "label_known_at": None,
        "current_association": False,
        "reasons": [],
    }
    if outcome_id is None:
        result["reasons"].append(
            policy.reason(
                "SAMPLE_OFFICIAL_TECHNICAL_LABEL_NOT_SELECTED",
                "尚未选择此确切实交的官方技术标签；未知不能补零，不能暗取其他结果。",
            )
        )
        return result
    row = c.execute(
        "SELECT * FROM design.outcomes WHERE bid_id=%s AND submission_id=%s AND id=%s",
        (bid, submission["id"], outcome_id),
    ).fetchone()
    if row is None:
        raise DomainError(
            "PACKAGE_TECHNICAL_OUTCOME_NOT_FOUND", "所选官方结果不属于该项目的确切实交", 404
        )
    view = outcomes.outcome_view(c, row)
    association = package_outcomes.current_reasons(c, submission, row, view["verification_details"])
    result.update(
        score_kind=view["score_kind"],
        label_known_at=view["known_at"],
        current_association=not association,
    )
    result["reasons"].extend(
        policy.reason(
            code.upper(), "官方标签的原实交、原件、核验或当前来源效力不满足关联条件。", outcome_id
        )
        for code in association
    )
    if view["score_kind"] != "technical_total" or view["value"] is None:
        result["reasons"].append(
            policy.reason(
                "SAMPLE_OFFICIAL_TECHNICAL_LABEL_REQUIRED",
                "综合分、未知或缺分值的结果不能用作官方技术标签。",
                outcome_id,
            )
        )
    else:
        # These are explicitly reported official values, not an input denominator.
        # A real official zero remains zero, never confused with a missing label.
        result["technical_value"] = policy.plain_decimal(view["value"])
        result["reported_maximum"] = policy.plain_decimal(view["maximum"])
    return result


def sample_context(c, scope, scope_id, submission_id, outcome_id=None, scale_id=None):
    scope = tuple(map(str, scope))
    _lock(c, scope)
    saved = scopes.load(c, scope, str(scope_id))
    row = c.execute(
        "SELECT s.*,h.submission_id AS head_id FROM design.submission_records s LEFT JOIN design.submission_heads h ON h.bid_id=s.bid_id WHERE s.bid_id=%s AND s.id=%s",
        (scope[0], submission_id),
    ).fetchone()
    if row is None:
        raise DomainError("PACKAGE_TECHNICAL_SUBMISSION_NOT_FOUND", "本项目没有所选实交记录", 404)
    if row["subject_kind"] != "bid_package":
        raise DomainError(
            "PACKAGE_TECHNICAL_SUBMISSION_SUBJECT_MISMATCH", "整包技术范围不能绑定单正文实交", 409
        )
    binding = package_outcomes.require_registration(c, row)
    # Validate the shared native record against its immutable binding too.
    submissions.value(row, binding)
    head = c.execute(
        "SELECT submission_id FROM design.submission_heads WHERE bid_id=%s", (scope[0],)
    ).fetchone()
    snapshot, error = _observe(c, scope, saved)
    maximum = _denominator(
        c,
        scope,
        saved,
        snapshot,
        str(scale_id) if scale_id else None,
        purpose="historical_backtest",
        submission_id=str(submission_id),
    )
    official = _official(c, scope[0], row, str(outcome_id) if outcome_id else None)
    value = policy.sample_context(
        saved,
        snapshot,
        clean(row),
        binding,
        official,
        maximum,
        observed_at=_time(c),
        submission_current=head is not None and str(head["submission_id"]) == str(submission_id),
        observation_error=error,
    )
    return value, _etag(value)


def _etag(value):
    # A read's wall-clock timestamp is informative; eligibility/source identities
    # determine the tag so repeated unchanged reads do not invent a new version.
    stable = {key: child for key, child in value.items() if key != "observed_at"}
    return etag("package-technical-eligibility", value["scope"]["scope_id"], sha(stable))
