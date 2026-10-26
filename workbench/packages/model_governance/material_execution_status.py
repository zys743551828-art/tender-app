"""Member-scoped read projection; observation never grants execution permission."""

from packages.domain.runtime import clean
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_qualification as policy
from packages.model_governance import material_qualified_jobs as qualified


def observe(c, row):
    receipt = qualified.observe(c, row)
    base = {
        "version": "material-execution-status/1",
        "intent_id": receipt["intent_id"],
        "actor_id": receipt["actor_id"],
        "scope_id": receipt["scope_id"],
        "job": receipt["job"],
        "request_digest": receipt["request_digest"],
        "task_state": receipt["state"],
        "send_authorized": False,
        "accuracy_verified": False,
        "invoice_reconciled": False,
    }
    if (
        c.execute(
            "SELECT to_regclass('material_qualification.execution_status') AS relation"
        ).fetchone()["relation"]
        is None
    ):
        return base | {"available": False, "reason": "EXECUTION_OBSERVER_UNAVAILABLE"}
    value = c.execute(
        "SELECT * FROM material_qualification.execution_status WHERE intent_id=%s AND actor_id=%s AND scope_id=%s AND bid_id=%s",
        (row["id"], row["actor_id"], row["scope_id"], row["bid_id"]),
    ).fetchone()
    if value is None or any(
        str(value[k]) != str(row[k if k != "intent_id" else "id"])
        for k in ("intent_id", "actor_id", "scope_id", "bid_id")
    ):
        policy.fail("STATUS_IDENTITY_INVALID", "执行观察身份不一致", 409)
    job = receipt["job"]
    if (job is None and value["job_id"] is not None) or (
        job is not None
        and (str(value["job_id"]) != job["job_id"] or value["job_digest"] != job["job_digest"])
    ):
        policy.fail("STATUS_IDENTITY_INVALID", "执行观察任务不一致", 409)
    state = value["execution_state"]
    counts = ("attempt_count", "unsettled_count", "unknown_count")
    amounts = ("reserved_minor", "held_minor", "known_estimated_minor", "released_minor")

    def integer(v):
        return type(v) is int and 0 <= v <= 2**53 - 1

    if (
        state not in execution.STATES | {None}
        or any(not integer(value[k]) for k in counts)
        or value["unsettled_count"] + value["unknown_count"] > value["attempt_count"]
    ):
        policy.fail("STATUS_INVALID", "执行账本状态异常", 409)
    if value["qualification_state"] not in {
        "approved",
        "changed",
        "revoked",
        "expired",
        "not_approved",
    }:
        policy.fail("STATUS_INVALID", "资格状态异常", 409)
    if state is None:
        if value["execution_mode"] is not None:
            policy.fail("STATUS_INVALID", "执行模式异常", 409)
        if (
            any(value[k] is not None for k in amounts)
            or value["currency"] is not None
            or value["attempt_count"]
        ):
            policy.fail("STATUS_INVALID", "执行账本缺失", 409)
        fee_state = "not_started"
    else:
        if (
            value["execution_mode"] not in {"qualified_live", "isolated_synthetic_mechanism"}
            or job is None
            or value["currency"] not in {"USD", "CNY"}
            or any(not integer(value[k]) for k in amounts)
        ):
            policy.fail("STATUS_INVALID", "执行费用异常", 409)
        fee_state = (
            "unknown"
            if value["unknown_count"] or state == "unknown"
            else "in_flight"
            if value["unsettled_count"] or state == "in_flight"
            else "reserved"
            if value["held_minor"]
            else "settled_estimate"
        )
    return clean(
        base
        | {
            "available": True,
            "qualification_state": value["qualification_state"],
            "execution_state": state or "not_started",
            "execution_mode": value["execution_mode"],
            "fee_state": fee_state,
            "currency": value["currency"],
            **{k: value[k] for k in counts + amounts},
            # Total invoice is never inferred from token usage or missing observations.
            "final_fee_minor": None,
            "last_settled_at": value["last_settled_at"],
            "observed_at": value["observed_at"],
        }
    )
