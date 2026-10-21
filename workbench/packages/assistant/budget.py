"""Assistant-only intent and aggregate budget protocol. No provider call or DDL here."""

from __future__ import annotations

import re
from uuid import UUID, uuid4

import httpx
import psycopg
from psycopg.types.json import Jsonb

from packages.assistant import intent_identity
from packages.domain.runtime import DomainError, clean, fetch, require_read_committed

PROTOCOL = "assistant-intent-budget/1"
ERRORS = {
    "ASSISTANT_REQUIRES_READ_COMMITTED",
    "ASSISTANT_TARGET_INVALID",
    "ASSISTANT_TARGET_IDENTITY_UNPROVEN",
    "ASSISTANT_INTENT_INVALID",
    "ASSISTANT_UNPRICED_OBLIGATION",
    "ASSISTANT_INDEPENDENCE_UNPROVEN",
    "ASSISTANT_EXPLICIT_NEW_QUESTION_REQUIRED",
    "ASSISTANT_PRICE_UNAVAILABLE",
    "ASSISTANT_BUDGET_NOT_CONFIGURED",
    "ASSISTANT_BUDGET_CURRENCY_UNRESOLVED",
    "ASSISTANT_BUDGET_EXHAUSTED",
    "ASSISTANT_CALL_REQUIRES_RECONCILIATION",
    "ASSISTANT_BUDGET_CONFIGURATION_CHANGED",
    "ASSISTANT_BUDGET_IDENTITY_INVALID",
    "ASSISTANT_EFFECT_IDENTITY_INVALID",
    "MODEL_EXECUTION_STALE",
    "ASSISTANT_USAGE_OUTSIDE_PRICE_BOUND",
    "ASSISTANT_RECONCILIATION_INVALID",
    "ASSISTANT_EXECUTION_NOT_TERMINAL",
    "ASSISTANT_USAGE_IDENTITY_INVALID",
}
UUID_TEXT = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def configured(c):
    return bool(
        c.execute(
            "SELECT to_regprocedure('design.assistant_reserve_budget(uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]
    )


def require(c):
    if not configured(c):
        raise DomainError(
            "ASSISTANT_BUDGET_NOT_CONFIGURED",
            "独立意图与聚合预算尚未配置，输入已保留，未发起新调用",
            503,
        )


def rpc(c, function, *arguments):
    from psycopg import sql

    if function not in {
        "assistant_reserve_budget",
        "assistant_dispatch_budget",
        "assistant_settle_budget",
        "assistant_observe_usage",
    }:
        raise ValueError("Unsupported assistant budget RPC")
    try:
        with c.transaction():
            return c.execute(
                sql.SQL("SELECT design.{}({}) AS value").format(
                    sql.Identifier(function),
                    sql.SQL(",").join(sql.Placeholder() for _ in arguments),
                ),
                arguments,
            ).fetchone()["value"]
    except psycopg.Error as error:
        code = error.diag.message_primary
        if code in ERRORS or (code and code.startswith("AUTHORING_PACKAGE_")):
            raise DomainError(
                code,
                "暂不能受理本次调用；请核对独立对象、预算配置或待核清账本，输入已保留",
                409,
                {"new_attempt_authorized": False},
            ) from None
        raise


def lock(c):
    require_read_committed(c)
    require(c)
    c.execute("SELECT pg_advisory_xact_lock(90129,1)")


def related_job(c, actor, body):
    """Explicit original references outrank new target labels, even embedded real IDs."""
    from packages.assistant import jobs

    ids = set()
    if body.get("related_job_id"):
        ids.add(UUID(body["related_job_id"]))
    action_ids = {UUID(body["related_action_id"])} if body.get("related_action_id") else set()
    for value in UUID_TEXT.findall(body.get("text", body.get("instruction", ""))):
        identity = UUID(value)
        if c.execute("SELECT 1 FROM assistant_jobs WHERE id=%s", (identity,)).fetchone():
            ids.add(identity)
        if c.execute(
            "SELECT 1 FROM assistant_action_links WHERE action_id=%s", (identity,)
        ).fetchone():
            action_ids.add(identity)
    for action in action_ids:
        row = fetch(c, "SELECT job_id FROM assistant_action_links WHERE action_id=%s", (action,))
        ids.add(row["job_id"])
    if len(ids) > 1:
        raise DomainError(
            "ASSISTANT_ORIGINAL_REFERENCE_AMBIGUOUS",
            "关联了多个原请求，尚不能证明独立；请明确原任务或保留输入待核清",
            409,
        )
    if ids:
        identity = next(iter(ids))
        jobs.authorize_job(c, jobs.job(c, identity), actor)
        return identity
    if body.get("request_mode") in {"retry", "continue"}:
        raise DomainError(
            "ASSISTANT_ORIGINAL_REFERENCE_REQUIRED", "重试或接续必须关联原任务，未重新发送", 422
        )
    return None


def checked_price(c, client):
    price = c.execute(
        "SELECT * FROM assistant_price_versions WHERE provider='deepseek' AND model=%s AND valid_from<=clock_timestamp() AND valid_until>clock_timestamp() ORDER BY verified_at DESC,created_at DESC,id DESC LIMIT 1",
        (client.model,),
    ).fetchone()
    if not price:
        raise DomainError(
            "ASSISTANT_PRICE_UNAVAILABLE", "缺少当前官方价格或输入硬上界，预算待核清，未发送", 409
        )
    if price["source_kind"] == "explicit_mock_fixture" and not isinstance(
        client._transport, httpx.MockTransport
    ):
        raise DomainError(
            "ASSISTANT_SYNTHETIC_PRICE_FORBIDDEN",
            "合成机制价格仅可用于显式MockTransport，不授权真实费用",
            409,
        )
    return price


def prepare(c, actor, body, bid=None, *, generation=False, explicit_send=False, origin_action=None):
    return _prepare(
        c,
        actor,
        body,
        bid,
        generation=generation,
        explicit_send=explicit_send,
        origin_action=origin_action,
    )


def prepare_package(c, actor, body, bid, input_id, input_digest):
    """Only a persisted input reference, never a caller-supplied target/proof.

    Final reserve/dispatch authority is the protected exact job binding in SQL.
    This shared preparation keeps legacy and exact requests in one fee scope.
    """
    return _prepare(
        c,
        actor,
        body,
        bid,
        generation=True,
        explicit_send=True,
        package_input=(input_id, input_digest),
    )


def _prepare(
    c,
    actor,
    body,
    bid=None,
    *,
    generation=False,
    explicit_send=False,
    origin_action=None,
    package_input=None,
):
    from packages.assistant import jobs
    from packages.domain.providers.deepseek import DeepSeekClient

    require_read_committed(c)
    related = related_job(c, actor, body)
    if related:
        return {"reuse_id": related}
    lock(c)
    if origin_action:
        old = c.execute(
            "SELECT job_id FROM assistant_logical_intents WHERE origin_action_id=%s",
            (origin_action,),
        ).fetchone()
        if old:
            jobs.authorize_job(c, jobs.job(c, old["job_id"]), actor)
            return {"reuse_id": old["job_id"]}
        link = fetch(
            c,
            "SELECT job_id,tool,state FROM assistant_action_links WHERE action_id=%s",
            (origin_action,),
        )
        source = jobs.job(c, link["job_id"])
        jobs.authorize_job(c, source, actor)
        if jobs.view(c, source["id"], actor)["requires_billing_reconciliation"]:
            return {"reuse_id": source["id"]}
        if link["tool"] != "authoring.generate" or link["state"] != "pending":
            raise DomainError(
                "ASSISTANT_EFFECT_IDENTITY_INVALID", "原操作卡不能被新问题重复执行", 409
            )
        explicit_send = True  # Trusted confirm path, not a body-supplied authorization.
    if package_input is None:
        target = intent_identity.resolve(c, actor, body, bid, generation=generation)
    else:
        from packages.authoring.package_job_identity import target as package_target

        target = package_target(c, bid, package_input[0], package_input[1])
    question, coarse, anti = intent_identity.keys(
        body.get("text", body.get("instruction", "")), target["target_key"], target["purpose"]
    )
    old = c.execute(
        "SELECT i.*,r.state AS budget_state FROM assistant_logical_intents i JOIN assistant_budget_reservations r ON r.job_id=i.job_id JOIN assistant_jobs j ON j.id=i.job_id WHERE i.coarse_key=%s AND (r.state IN ('held','sent','unknown') OR EXISTS(SELECT FROM operations o WHERE o.id=j.operation_id AND o.state IN ('queued','running','cancel_requested')) OR EXISTS(SELECT FROM assistant_global_runs run WHERE run.id=j.id AND run.state IN ('queued','running','cancel_requested'))) ORDER BY i.created_at,i.id LIMIT 1",
        (coarse,),
    ).fetchone()
    if old:
        if old["anti_resend_key"] == anti:
            source = jobs.job(c, old["job_id"])
            if source["scope"] != "global" or source["actor_id"] == actor:
                jobs.authorize_job(c, source, actor)
                return {"reuse_id": source["id"]}
        raise DomainError(
            "ASSISTANT_INDEPENDENCE_UNPROVEN",
            "暂不能确认这与待核清请求无关，输入已保留。请选择明确的新对象／用途，或等待原请求核清",
            409,
            {"same_target_and_purpose": True, "new_attempt_authorized": False},
        )
    pending = c.execute(
        "SELECT 1 FROM assistant_budget_reservations r JOIN assistant_jobs j ON j.id=r.job_id WHERE r.actor_id=%s AND (r.state IN ('sent','unknown') OR EXISTS(SELECT FROM assistant_global_calls call WHERE call.run_id=j.id AND call.state IN ('reserved','unknown')) OR EXISTS(SELECT FROM model_calls call WHERE call.operation_id=j.operation_id AND call.state IN ('reserved','unknown'))) LIMIT 1",
        (actor,),
    ).fetchone()
    if pending and (
        not explicit_send
        or question.rstrip("。.!！?？")
        in {"继续", "请继续", "重试", "还有呢", "同问", "继续上次", "重试上次"}
    ):
        raise DomainError(
            "ASSISTANT_ORIGINAL_REFERENCE_REQUIRED",
            "已有待核清调用；接续必须关联原任务，新问题须明确新的业务对象／用途",
            409,
        )
    price = checked_price(c, DeepSeekClient.from_env())
    return {
        "id": str(uuid4()),
        "request_mode": "new_question",
        "normalized_question": question,
        "target": target,
        "coarse_key": coarse,
        "anti_resend_key": anti,
        "explicit_send": bool(explicit_send),
        "origin_action_id": str(origin_action) if origin_action else None,
        "price_version_id": str(price["id"]),
        "profile": {
            "provider": price["provider"],
            "model": price["model"],
            "purpose": "authoring" if generation else "assistant",
            "port": "generation/1",
            "formal_scoring_eligible": False,
        },
    }


def bind(c, job_id, actor, prepared):
    target = prepared["target"]
    c.execute(
        """INSERT INTO assistant_logical_intents(id,job_id,actor_id,request_mode,normalized_question,purpose,target_key,coarse_key,anti_resend_key,canonical_project_key,target,explicit_send,origin_action_id)
        VALUES(%s,%s,%s,'new_question',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            UUID(prepared["id"]),
            job_id,
            actor,
            prepared["normalized_question"],
            target["purpose"],
            target["target_key"],
            prepared["coarse_key"],
            prepared["anti_resend_key"],
            target["canonical_project_key"],
            Jsonb(target),
            prepared["explicit_send"],
            UUID(prepared["origin_action_id"]) if prepared["origin_action_id"] else None,
        ),
    )
    return rpc(c, "assistant_reserve_budget", job_id)


def projection(c, job_id):
    if not configured(c):
        return None
    value = c.execute(
        "SELECT r.*,p.version AS price_version,p.amount_scale,p.source_kind,p.input_per_million_minor,p.output_per_million_minor FROM assistant_budget_reservations r JOIN assistant_price_versions p ON p.id=r.price_id WHERE job_id=%s",
        (job_id,),
    ).fetchone()
    return (
        clean(value)
        | {"estimate_not_provider_spend_cap": True, "unknown_hold_released_automatically": False}
        if value
        else None
    )


def before_send(c, row, call_id, request, client):
    require(c)
    manifest = row["input_manifest"]
    frozen = manifest.get("logical_intent")
    if not frozen:
        raise DomainError(
            "ASSISTANT_UNPRICED_OBLIGATION", "旧调用无可信价格或聚合上限，未安排新调用", 409
        )
    price = fetch(
        c, "SELECT * FROM assistant_price_versions WHERE id=%s", (UUID(frozen["price_version_id"]),)
    )
    expected = frozen["profile"]
    if (
        expected["model"] != client.model
        or expected["purpose"] != ("assistant" if row["kind"] == "answer" else "authoring")
        or request["max_tokens"] != manifest["request"].get("max_tokens", 2048)
    ):
        raise DomainError(
            "ASSISTANT_EXECUTION_PROFILE_CHANGED",
            "冻结用途或模型配置已变，不能借新profile重发",
            409,
        )
    if price["source_kind"] == "explicit_mock_fixture" and not isinstance(
        client._transport, httpx.MockTransport
    ):
        raise DomainError("ASSISTANT_SYNTHETIC_PRICE_FORBIDDEN", "合成价格不能用于真实请求", 409)
    return rpc(c, "assistant_dispatch_budget", row["id"], call_id)


def before_native_reserve(c, row, profile, max_tokens):
    lock(c)
    frozen = row["input_manifest"].get("logical_intent")
    if not frozen or frozen["profile"] != profile:
        raise DomainError(
            "ASSISTANT_EXECUTION_PROFILE_CHANGED",
            "原意图或冻结profile不符，未创建新的调用预留",
            409,
        )
    hold = fetch(
        c,
        "SELECT * FROM assistant_budget_reservations WHERE job_id=%s AND intent_id=%s",
        (row["id"], UUID(frozen["id"])),
    )
    if hold["price_id"] != UUID(frozen["price_version_id"]) or hold["output_upper"] != max_tokens:
        raise DomainError(
            "ASSISTANT_BUDGET_IDENTITY_INVALID", "聚合预留与原输入不符，未创建新的调用预留", 409
        )
    return hold


def settle(c, job_id):
    if (
        configured(c)
        and c.execute(
            "SELECT 1 FROM assistant_budget_reservations WHERE job_id=%s", (job_id,)
        ).fetchone()
    ):
        return rpc(c, "assistant_settle_budget", job_id)
    return None


def observe_usage(c, job_id, call_id, usage, request_id):
    value = rpc(c, "assistant_observe_usage", job_id, call_id, Jsonb(usage), request_id)
    if value["state"] == "unknown":
        raise DomainError(
            "ASSISTANT_USAGE_REQUIRES_RECONCILIATION",
            "已记录实际usage，但与冻结上界或可信核清冲突；旧结果未发布，原预留仍占用",
            409,
        )
    return value


def terminal_tick(c, ids):
    if not configured(c):
        return
    for identity in ids:
        settle(c, identity)
