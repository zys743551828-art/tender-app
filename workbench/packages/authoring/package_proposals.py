"""Explicit adoption of a protected published B2 action; original IO outside locks."""

from uuid import UUID

from psycopg.types.json import Jsonb

from packages.assistant import actions, jobs
from packages.authoring import exact_sources, package_admission, package_generation
from packages.authoring import package_input_repository as inputs
from packages.authoring.package_publication import inspect
from packages.domain.bid_package_service import lock_bid
from packages.domain.runtime import (
    ROOT,
    Command,
    DomainError,
    audit,
    clean,
    connection,
    fetch,
    sha,
)

KIND = "assistant-action-resolve"


def policy():
    paths = (
        "packages/authoring/package_proposals.py",
        "packages/authoring/exact_sources.py",
        "packages/authoring/exact_revision_contracts.py",
        "packages/contracts/sql/authoring-exact-revisions.sql",
        "packages/authoring/repository.py",
        "packages/authoring/snapshot_structure.py",
    )
    return {
        "protocol": "authoring-exact-adoption-policy/1",
        "supported_content": "plain_text_stable_node",
        "source_sha256": {name: sha((ROOT / name).read_bytes()) for name in paths},
    }


def preview(c, identity):
    from packages.authoring.package_publication import preview as candidate_preview

    result = candidate_preview(c, identity)
    ready = exact_sources.apply_available(c)
    return result | {
        "apply_available": ready,
        "build_available": False,
        "effect": "明确采用会追加正文修订及固定整包来源资格；不表示内容正确或文件已完成"
        if ready
        else result["effect"],
    }


def _checked_receipt(c, command, action, actor, key, condition):
    if command["request_digest"] != sha({"body": {"decision": "confirm"}, "if_match": condition}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一操作键对应另一份候选确认", 409)
    stored = command["response"]
    if stored is None:
        raise DomainError("COMMAND_INCOMPLETE", "原采用尚未完成", 409)
    actual, job = inspect(c, action)
    consumption = fetch(c, "SELECT * FROM design.action_consumptions WHERE action_id=%s", (action,))
    body = stored.get("body", {})
    if (
        stored.get("status") != 200
        or stored.get("headers", {}).get("ETag") != actions.tag(body)
        or body.get("action_id") != str(action)
        or body.get("job_id") != str(job["id"])
        or body.get("target_bid_id") != str(actual["bid_id"])
        or body.get("request_digest") != actual["request_digest"]
        or body.get("result") != consumption["result"]
        or body.get("resolved_by") != str(consumption["consumed_by"])
        or command["actor_id"] != UUID(str(actor))
        or command["command_kind"] != KIND
        or command["target_id"] != UUID(str(action))
        or command["idempotency_key"] != key
    ):
        raise DomainError("AUTHORING_EXACT_RECEIPT_INVALID", "原采用回执与真实操作关系不符", 409)
    resolution = consumption["result"].get("assistant_resolution", {})
    if body.get("state") != resolution.get("state"):
        raise DomainError("AUTHORING_EXACT_RECEIPT_INVALID", "原采用状态与消费记录不符", 409)
    if resolution.get("state") == "executed":
        q = fetch(
            c,
            "SELECT section_revision_id FROM design.authoring_exact_revisions WHERE action_id=%s",
            (action,),
        )
        exact_sources.load(c, actual["bid_id"], q["section_revision_id"])
    return stored


def replay(c, actor, action, key, condition):
    old = c.execute(
        "SELECT * FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, KIND, action, key),
    ).fetchone()
    return _checked_receipt(c, old, action, actor, key, condition) if old else None


def _pending(c, identity, condition):
    actual, job = inspect(c, identity)
    current = actions.view(c, identity)
    if not condition:
        raise DomainError("PRECONDITION_REQUIRED", "请先读取明确操作卡再确认采用", 428)
    if condition != actions.tag(current):
        raise DomainError("REVISION_CONFLICT", "操作卡已变化，请保留原选择并重新核对", 412)
    if actual["expires_at"] <= fetch(c, "SELECT clock_timestamp() AS at")["at"]:
        raise DomainError("ACTION_EXPIRED", "候选已过期，原草稿已保留", 409)
    if current["state"] != "pending":
        raise DomainError("ACTION_CONSUMED", "该候选已有明确处理结果", 409)
    if jobs.view(c, job["id"])["requires_billing_reconciliation"]:
        raise DomainError("MODEL_CALL_REQUIRES_RECONCILIATION", "原调用费用尚未核清", 409)
    return actual, job, current


def _observed(action, condition):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        actual, job, before = _pending(c, action, condition)
        row = inputs.load(c, actual["bid_id"], actual["input_id"])
        inputs.declarations_match(c, row)
        observed = package_admission.capture(c, str(actual["bid_id"]), row["manifest"]["selection"])
        if observed._context_text != row["context_text"]:
            raise DomainError("AUTHORING_PACKAGE_INPUT_CHANGED", "候选的原固定输入资格已变化", 409)
        package_generation.checked(job["input_manifest"], live_policy=True)
        return observed, before


def _append(c, actual, job, before, actor, command, condition):
    """Adopt through the same draft CAS, section append and freeze as ordinary saves."""
    from packages.authoring.repository import draft_etag, save_draft

    frozen = package_generation.checked(job["input_manifest"], live_policy=True)
    target = frozen["target"]
    content = package_generation.materialize(frozen, actual["payload"]["candidate"])["after"]
    admission = exact_sources.ExactAdoption(
        action_id=actual["id"],
        command_id=command,
        actor_id=UUID(str(actor)),
        condition=condition,
        before_action=before,
    )
    saved = save_draft(
        c,
        actual["bid_id"],
        UUID(target["draft_id"]),
        actor,
        {
            "base_draft_revision": target["base_draft_revision"],
            "changes": [
                {
                    "section_id": target["section_id"],
                    "base_section_revision": target["base_section_revision"],
                    "schema_digest": target["schema_digest"],
                    "content": content,
                }
            ],
        },
        draft_etag(target["draft_id"], target["base_draft_revision"]),
        exact_admission=admission,
    )
    qualification_view = fetch(
        c,
        "SELECT digest FROM design.authoring_exact_revisions WHERE id=%s",
        (admission.qualification_id,),
    )
    result = clean(
        {
            "assistant_resolution": {
                "action_id": actual["id"],
                "state": "executed",
                "tool": "authoring.apply_patch",
                "target_bid_id": actual["bid_id"],
                "domain_result": saved,
                "error_code": None,
                "http_status": 200,
                "business_effect_executed": True,
            }
        }
    )
    c.execute(
        "INSERT INTO design.action_consumptions(action_id,command_id,consumed_by,result) VALUES(%s,%s,%s,%s)",
        (actual["id"], command, actor, Jsonb(result)),
    )
    c.execute(
        "UPDATE design.assistant_action_links SET state='executed',revision=revision+1,resolved_by=%s,resolved_at=clock_timestamp(),error_code=NULL WHERE action_id=%s",
        (actor, actual["id"]),
    )
    audit(
        c,
        actor,
        actual["bid_id"],
        "authoring.exact_candidate_adopted",
        {
            "action_id": actual["id"],
            "qualification_id": admission.qualification_id,
            "qualification_digest": qualification_view["digest"],
            "section_revision_id": admission.section_revision_id,
            "snapshot_id": saved["snapshot_id"],
            "snapshot_digest": saved["snapshot_digest"],
        },
        command,
    )
    return actions.view(c, actual["id"])


def resolve(actor, action, key, condition, *, final_auth):
    def authorize():
        current = final_auth()
        current_actor = current["member_id"] if isinstance(current, dict) else current
        if UUID(str(current_actor)) != UUID(str(actor)):
            raise DomainError("AUTHORING_EXACT_ACTOR_CHANGED", "采用期间操作者身份已变化", 403)

    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的采用幂等键", 428)
    with exact_sources.errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        exact_sources.require_schema(c)
        old = replay(c, actor, action, key, condition)
        if old:
            return old, True
        actual, _ = inspect(c, action)
        consumed = bool(
            c.execute(
                "SELECT 1 FROM design.action_consumptions WHERE action_id=%s", (action,)
            ).fetchone()
        )
        if not consumed:
            exact_sources.require_apply(c)
        bid = actual["bid_id"]
    # A globally consumed candidate never rechecks bytes or creates another revision.
    verified = None
    if not consumed:
        try:
            verified = package_admission.verify(_observed(action, condition)[0])
        except DomainError:
            # A concurrent confirmation may have advanced the target while originals were read.
            # Reuse only its actual global consumption; otherwise retain the original rejection.
            with connection() as c:
                if not c.execute(
                    "SELECT 1 FROM design.action_consumptions WHERE action_id=%s", (action,)
                ).fetchone():
                    raise
    with exact_sources.errors(), connection() as c:
        lock_bid(c, bid)
        command = Command(c, actor, KIND, action, key, {"decision": "confirm"}, condition)
        if command.replay:
            return replay(c, actor, action, key, condition), True
        actions.lock(c, action)
        if c.execute(
            "SELECT 1 FROM design.action_consumptions WHERE action_id=%s", (action,)
        ).fetchone():
            value = actions.view(c, action)
            authorize()
            return command.finish(value, 200, {"ETag": actions.tag(value)}), False
        if verified is None:
            raise DomainError("AUTHORING_EXACT_CONSUMPTION_MISSING", "原操作消费记录未能核验", 409)
        package_admission.recheck(c, verified)
        actual, job, before = _pending(c, action, condition)
        inputs.declarations_match(c, inputs.load(c, bid, actual["input_id"]))
        authorize()
        value = _append(c, actual, job, before, actor, command.id, condition)
        stored = command.finish(value, 200, {"ETag": actions.tag(value)})
    return stored, False
