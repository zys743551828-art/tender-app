"""Explicit, bounded authoring batches on the existing assistant execution ledger.

All mutations run inside the caller's READ COMMITTED transaction. Provider I/O
remains exclusively in the existing worker, after the whole batch is committed.
"""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID

from psycopg.types.json import Jsonb

from packages.assistant import budget, context, jobs
from packages.assistant import generation_batch_contracts as contracts
from packages.authoring import repository
from packages.authoring.patches import proposal_context
from packages.domain.runtime import DomainError, audit, clean, fetch, match, now, sha, uid
from packages.domain.work_access import begin

CREATE_KIND = "create-authoring-generation-batch"
RETRY_KIND = "retry-authoring-generation-batch"
RESOLVE_KIND = "resolve-authoring-generation-batch"
PROTOCOL = "authoring-generation-batch/1"
TERMINAL = {"succeeded", "failed", "cancelled"}
TABLES = (
    "assistant_generation_batches",
    "assistant_generation_batch_attempts",
    "assistant_generation_batch_resolutions",
)


def require_schema(c):
    jobs.require_schema(c)
    budget.require(c)
    for table in TABLES:
        relation = "design." + table
        if c.execute("SELECT to_regclass(%s) AS id", (relation,)).fetchone()[
            "id"
        ] is None or not all(
            c.execute(
                "SELECT has_table_privilege(current_user,%s,%s) AS ok", (relation, permission)
            ).fetchone()["ok"]
            for permission in ("SELECT", "INSERT")
        ):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_NOT_CONFIGURED",
                "尚未配置章节批次扩展及分离角色授权",
                503,
            )


def amount(value):
    if type(value) is not int or not 0 <= value <= contracts.MAX_MINOR:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_AMOUNT_UNREPRESENTABLE",
            "费用超出可精确表示的整数范围，请查看原账本并核定预算",
            409,
        )
    return value


def price_view(price):
    return clean(
        {
            "price_version_id": price["id"],
            "version": price["version"],
            "provider": price["provider"],
            "model": price["model"],
            "currency": price["currency"],
            "amount_scale": price["amount_scale"],
            "input_upper": price["input_hard_ceiling"],
            "output_upper": price["output_hard_ceiling"],
            "input_per_million_minor": amount(price["input_per_million_minor"]),
            "output_per_million_minor": amount(price["output_per_million_minor"]),
            "valid_until": price["valid_until"],
            "source_kind": price["source_kind"],
            "source_uri": price["source_uri"],
            "source_sha256": price["source_sha256"],
        }
    )


def reservation_estimate(price, tokens):
    if type(tokens) is not int or not 1 <= tokens <= min(8192, price["output_upper"]):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_OUTPUT_LIMIT", "输出令牌数超出该价格版本的实际上限", 422
        )
    return amount(
        (
            price["input_upper"] * price["input_per_million_minor"]
            + tokens * price["output_per_million_minor"]
            + 999999
        )
        // 1000000
    )


def current_price(c):
    from packages.domain.providers.deepseek import DeepSeekClient

    return price_view(budget.checked_price(c, DeepSeekClient.from_env()))


def capabilities(c):
    unavailable = None
    price = None
    estimates = []
    default = 2048
    try:
        require_schema(c)
        price = current_price(c)
        default = min(default, price["output_upper"])
        ceilings = {min(8192, price["output_upper"]), default, 512, 1024, 2048, 4096, 8192}
        estimates = [
            {"max_tokens": n, "reservation_minor": reservation_estimate(price, n)}
            for n in sorted(ceilings)
            if 1 <= n <= min(8192, price["output_upper"])
        ]
    except DomainError as error:
        unavailable = {"code": error.code, "message": error.message}
    return {
        "enabled": unavailable is None,
        "unavailable_reason": unavailable,
        "generation_mode": contracts.MODE,
        "max_sections": contracts.MAX_SECTIONS,
        "max_attempts_per_section": contracts.MAX_ATTEMPTS,
        "max_frozen_bytes": contracts.MAX_FROZEN_BYTES,
        "max_instruction_chars": 8000,
        "max_limit_minor": contracts.MAX_MINOR,
        "amount_scale": contracts.SCALE,
        "default_max_tokens": default,
        "price": price,
        "estimates": estimates,
        "requires_explicit_selection": True,
        "atomic_apply": True,
        "requires_verified_identity": True,
        "automatic_retry_authorized": False,
    }


def scoped(bid, draft, body):
    return {"bid_id": str(bid), "draft_id": str(draft), **body}


def binding(command, actor, key, body, condition, bid, draft):
    return {
        "command_id": str(command.id),
        "actor_id": str(actor),
        "idempotency_key": key,
        "request_digest": sha({"body": scoped(bid, draft, body), "if_match": condition}),
        "request": deepcopy(body),
        "if_match": condition,
    }


def start(c, bid, draft, actor, key, body, condition, kind, target, *, work=True):
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(ch) < 32 for ch in key):
        raise DomainError("IDEMPOTENCY_REQUIRED", "请保留有效的批次操作幂等键", 428)
    command = begin(
        c, actor, kind, target, key, scoped(bid, draft, body), condition, bid=bid, work=work
    )
    if command.replay and (
        command.replay["body"].get("bid_id") != str(bid)
        or command.replay["body"].get("draft_id") != str(draft)
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_SCOPE_MISMATCH", "回执不属于当前项目草稿", 409
        )
    return command


def row_for(c, bid, draft, identity):
    row = fetch(
        c,
        """SELECT b.*,r.result AS resolution,r.digest AS resolution_digest
        FROM assistant_generation_batches b
        LEFT JOIN assistant_generation_batch_resolutions r ON r.batch_id=b.id
        WHERE b.bid_id=%s AND b.draft_id=%s AND b.id=%s""",
        (bid, draft, identity),
    )
    if sha(row["manifest"]) != row["digest"] or (
        row["resolution"] is not None and sha(row["resolution"]) != row["resolution_digest"]
    ):
        raise DomainError("AUTHORING_GENERATION_BATCH_CORRUPTED", "批次或处理回执摘要不一致", 409)
    return row


def assert_open(row, digest=None):
    if digest is not None and digest != row["digest"]:
        raise DomainError("AUTHORING_GENERATION_BATCH_CHANGED", "批次身份与当前请求不一致", 409)
    if row["resolution"] is not None:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_RESOLVED", "批次已有最终处理结果，请读取原回执", 409
        )


def target(c, bid, draft, revision, condition):
    head = repository.lock_draft(c, bid, draft)
    match(condition, "draft", draft, head["revision"])
    if revision != head["revision"]:
        raise DomainError("DRAFT_REVISION_CONFLICT", "正文草稿已变化，请保存并重新建立批次", 412)
    snapshot = fetch(
        c,
        "SELECT id,digest,manifest FROM draft_snapshots WHERE bid_id=%s AND draft_id=%s AND revision=%s",
        (bid, draft, revision),
    )
    if sha(snapshot["manifest"]) != snapshot["digest"]:
        raise DomainError("DRAFT_SNAPSHOT_CORRUPT", "草稿快照校验失败", 409)
    return {
        "base_draft_revision": revision,
        "base_snapshot_id": str(snapshot["id"]),
        "base_snapshot_digest": snapshot["digest"],
        "base_draft_etag": repository.draft_etag(draft, revision),
        "context": proposal_context(c, bid),
    }


def assert_target(c, bid, draft, row, condition):
    current = target(c, bid, draft, row["base_draft_revision"], condition)
    if current != row["manifest"]["target"]:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_CONTEXT_CHANGED",
            "批次冻结的草稿、要求或事实已经变化，请重新预览",
            409,
        )


def generation_request(section):
    return {
        key: deepcopy(section[key])
        for key in (
            "section_id",
            "base_section_revision",
            "instruction",
            "source_version_ids",
            "max_tokens",
        )
    }


def record_attempt(
    c, bid, draft, batch, actor, command, section, number, price, *, previous_job=None
):
    from packages.authoring import section_patch_set

    batch_context = {"batch_id": str(batch), "section_id": section["section_id"], "attempt": number}
    try:
        queued = jobs.queue_generation(
            c,
            bid,
            actor,
            generation_request(section),
            command.id,
            explicit_send=True,
            generation_mode=contracts.MODE,
            batch_context=batch_context,
            generation_scope=section["selected_node_ids"],
        )
    except DomainError as error:
        if error.code == "ASSISTANT_INDEPENDENCE_UNPROVEN":
            related = c.execute(
                """SELECT DISTINCT j.id AS job_id,i.target->>'id' AS section_id
                FROM assistant_logical_intents i JOIN assistant_jobs j ON j.id=i.job_id
                JOIN assistant_budget_reservations r ON r.job_id=i.job_id JOIN operations op ON op.id=j.operation_id
                WHERE j.bid_id=%s AND i.target->>'kind'='section' AND i.purpose='section_draft'
                AND (r.state IN ('held','sent','unknown') OR op.state IN ('queued','running','cancel_requested'))
                AND ((i.target->>'id')::uuid=%s OR EXISTS(SELECT 1 FROM section_revisions a JOIN section_revisions b ON a.digest=b.digest
                    WHERE a.section_id=(i.target->>'id')::uuid AND b.section_id=%s))""",
                (bid, UUID(section["section_id"]), UUID(section["section_id"])),
            ).fetchall()
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_INDEPENDENCE_UNPROVEN",
                "这些章节的输入不足以证明独立生成；请核对具体章节与原任务，待原费用核清后分批审查。相同内容的章节仅修改指令或来源不能绕过该限制",
                409,
                {
                    "section_ids": sorted(
                        {section["section_id"], *[r["section_id"] for r in related]}
                    ),
                    "existing_job_ids": [str(r["job_id"]) for r in related],
                    "new_attempt_authorized": False,
                },
            ) from None
        raise
    job = jobs.job(c, UUID(queued["id"]))
    frozen = job["input_manifest"]
    if (
        frozen.get("generation_mode") != contracts.MODE
        or frozen.get("batch_context") != batch_context
        or frozen["request"] != generation_request(section)
        or job["actor_id"] != actor
        or frozen["logical_intent"]["price_version_id"] != price["price_version_id"]
        or job["bid_id"] != bid
        or job["scope"] != "project"
        or job["kind"] != "authoring"
        or frozen["plan"]["section_digest"] != section["before_digest"]
        or frozen["plan"]["patch_scope"]
        != section_patch_set.freeze_scope(
            frozen["plan"]["original_content"], section["selected_node_ids"]
        )
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_JOB_REUSED",
            "已有任务不能移入本批次或替代本次冻结输入，请核对原任务",
            409,
        )
    # Retries may not silently refresh offered evidence, verified facts or scope.
    plan_digest = sha({"plan": frozen["plan"], "project_memory": frozen["project_memory"]})
    if section.get("plan_digest", plan_digest) != plan_digest:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_SOURCE_CHANGED",
            "来源、章节范围或项目事实与原批次不同，请建立新批次",
            409,
        )
    hold = budget.projection(c, job["id"])
    if (
        hold is None
        or hold["price_id"] != price["price_version_id"]
        or hold["currency"] != price["currency"]
        or hold["amount_scale"] != price["amount_scale"]
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_PRICE_CHANGED", "任务预留与已确认价格或币种不一致", 409
        )
    c.execute(
        """INSERT INTO assistant_generation_batch_attempts(batch_id,bid_id,draft_id,section_id,attempt,
        job_id,writing_plan_id,command_id,created_by,previous_job_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            batch,
            bid,
            draft,
            UUID(section["section_id"]),
            number,
            job["id"],
            job["writing_plan_id"],
            command.id,
            actor,
            previous_job,
        ),
    )
    return str(job["id"]), plan_digest


def receipt(row, command_binding, kind, *, jobs_created=(), selected=(), saved=None):
    selected_set = set(selected)
    saved = saved or {}
    return {
        "protocol": "authoring-generation-batch-command/1",
        "bid_id": str(row["bid_id"]),
        "draft_id": str(row["draft_id"]),
        "batch_id": str(row["id"]),
        "batch_digest": row["digest"],
        "kind": kind,
        "batch_state": kind if kind in {"applied", "rejected"} else "open",
        "created_job_ids": list(jobs_created),
        "applied_section_ids": list(selected),
        "unselected_section_ids": [
            s["section_id"]
            for s in row["manifest"]["sections"]
            if s["section_id"] not in selected_set
        ]
        if kind in {"applied", "rejected"}
        else [],
        "draft_revision": saved.get("draft_revision"),
        "snapshot_id": saved.get("snapshot_id"),
        "snapshot_digest": saved.get("snapshot_digest"),
        "recorded_at": now().isoformat(),
        "command": command_binding,
    }


def create(c, bid, draft, actor, key, body, condition):
    contracts.validate("AuthoringGenerationBatchCreateRequest", body)
    with c.transaction():
        command = start(c, bid, draft, actor, key, body, condition, CREATE_KIND, draft)
        if command.replay:
            return command.replay, True
        require_schema(c)
        ids = [s["section_id"] for s in body["sections"]]
        if len(ids) != len(set(ids)):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_SECTION_DUPLICATE", "同一批次不能重复选择章节", 422
            )
        if sum(s["budget_limit_minor"] for s in body["sections"]) > body["total_limit_minor"]:
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_BUDGET_INVALID", "各章累计预算之和不能超过批次总额", 422
            )
        frozen_target = target(c, bid, draft, body["base_draft_revision"], condition)
        context.lock_scope(c, [bid])
        price = current_price(c)
        if any(body[k] != price[k] for k in ("price_version_id", "currency", "amount_scale")):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_PRICE_CHANGED",
                "当前价格身份已变化，请重新确认价格与预算",
                409,
            )
        current = {str(s["section_id"]): s for s in repository.latest_sections(c, bid, draft)}
        sections = []
        for selected in body["sections"]:
            source = current.get(selected["section_id"])
            if source is None:
                raise DomainError(
                    "AUTHORING_GENERATION_BATCH_SECTION_UNAVAILABLE",
                    "所选章节不属于当前草稿的活动范围",
                    409,
                )
            if (
                source["revision"] != selected["base_section_revision"]
                or sha(source["content"]) != source["digest"]
            ):
                raise DomainError("SECTION_REVISION_CONFLICT", "章节基线已变化，请重新选择", 412)
            if reservation_estimate(price, selected["max_tokens"]) > selected["budget_limit_minor"]:
                raise DomainError(
                    "AUTHORING_GENERATION_BATCH_BUDGET_INSUFFICIENT",
                    "章节额度不足以预留本次完整输入与输出上界",
                    409,
                    {"section_ids": [selected["section_id"]]},
                )
            sections.append(
                deepcopy(selected)
                | {
                    "title": source["content"]["attrs"]["title"],
                    "ordinal": source["content"]["attrs"]["ordinal"],
                    "before_digest": source["digest"],
                }
            )
        identity = uid()
        new_jobs = []
        for section in sections:
            job_id, plan_digest = record_attempt(
                c, bid, draft, identity, actor, command, section, 1, price
            )
            new_jobs.append(job_id)
            section["plan_digest"] = plan_digest
        assert_frozen_size(c, identity)
        manifest = {
            "protocol": PROTOCOL,
            "generation_mode": contracts.MODE,
            "batch_id": str(identity),
            "bid_id": str(bid),
            "draft_id": str(draft),
            "target": frozen_target,
            "price": price,
            "request": deepcopy(body),
            "sections": sections,
            "preparation": binding(command, actor, key, body, condition, bid, draft),
        }
        if (
            len(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            > contracts.MAX_FROZEN_BYTES
        ):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_TOO_LARGE",
                "批次冻结输入超过范围，请减少章节或来源",
                422,
            )
        # Attempts refer to this header through a deferred FK, so no partial
        # header, reservation or Kafka outbox item can escape a failed batch.
        c.execute(
            """INSERT INTO assistant_generation_batches(id,bid_id,draft_id,base_draft_revision,
            base_snapshot_id,command_id,created_by,manifest,digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                identity,
                bid,
                draft,
                body["base_draft_revision"],
                UUID(frozen_target["base_snapshot_id"]),
                command.id,
                actor,
                Jsonb(manifest),
                sha(manifest),
            ),
        )
        row = row_for(c, bid, draft, identity)
        assert_budget(c, row)
        result = receipt(row, manifest["preparation"], "created", jobs_created=new_jobs)
        audit(
            c,
            actor,
            bid,
            "authoring.generation_batch_created",
            {"batch_id": str(identity), "batch_digest": row["digest"], "draft_id": str(draft)},
            command.id,
        )
        return command.finish(result, 201, {"ETag": frozen_target["base_draft_etag"]}), False


ATTEMPT_SELECT = """SELECT a.*,j.operation_id,o.state,
    coalesce(p.state,'pending') AS publication_state,p.action_id,p.error_code,
    action.request_digest AS candidate_digest,link.state AS action_state,action.expires_at,
    r.state AS budget_state,r.reserved_minor,r.charged_minor,r.currency,r.price_id,
    r.requires_manual_reconciliation,
    EXISTS(SELECT 1 FROM model_calls mc WHERE mc.operation_id=o.id AND mc.state IN ('reserved','unknown')) AS unresolved_call
    FROM assistant_generation_batch_attempts a
    JOIN assistant_jobs j ON j.id=a.job_id JOIN operations o ON o.id=j.operation_id
    JOIN assistant_budget_reservations r ON r.job_id=j.id
    LEFT JOIN assistant_publications p ON p.job_id=j.id
    LEFT JOIN proposed_actions action ON action.id=p.action_id
    LEFT JOIN assistant_action_links link ON link.action_id=p.action_id AND link.job_id=j.id"""


def attempts(c, identity):
    return c.execute(
        ATTEMPT_SELECT + " WHERE a.batch_id=%s ORDER BY a.section_id,a.attempt", (identity,)
    ).fetchall()


def budget_view(rows, limit, currency):
    charged = 0
    reserved = 0
    unresolved = False
    for r in rows:
        if r["currency"] != currency:
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_PRICE_CHANGED", "批次账本出现不同币种，必须先核清", 409
            )
        amount(r["reserved_minor"])
        if r["charged_minor"] is not None:
            amount(r["charged_minor"])
        if r["budget_state"] in {"settled", "released"}:
            if r["charged_minor"] is None:
                raise DomainError(
                    "AUTHORING_GENERATION_BATCH_LEDGER_INCOMPLETE", "费用终态缺少核定金额", 409
                )
            charged += r["charged_minor"]
        else:
            reserved += r["reserved_minor"]
        unresolved |= bool(
            r["unresolved_call"]
            or r["requires_manual_reconciliation"]
            or r["budget_state"] in {"sent", "unknown"}
        )
    charged, reserved = amount(charged), amount(reserved)
    exposure = amount(charged + reserved)
    return {
        "currency": currency,
        "amount_scale": contracts.SCALE,
        "limit_minor": amount(limit),
        "charged_minor": charged,
        "reserved_minor": reserved,
        "exposure_minor": exposure,
        "remaining_minor": max(0, limit - exposure),
        "requires_reconciliation": unresolved,
        "over_limit": exposure > limit,
        "estimate_not_provider_spend_cap": True,
    }


def assert_budget(c, row, *, next_section=None):
    rows = attempts(c, row["id"])
    manifest = row["manifest"]
    price = manifest["price"]
    if any(str(r["price_id"]) != price["price_version_id"] for r in rows):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_PRICE_CHANGED", "批次预留未使用同一冻结价格版本", 409
        )
    total = budget_view(rows, manifest["request"]["total_limit_minor"], price["currency"])
    extra = reservation_estimate(price, next_section["max_tokens"]) if next_section else 0
    if total["over_limit"] or total["remaining_minor"] < extra:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_BUDGET_INSUFFICIENT",
            "批次累计费用与保留预留已达到总额",
            409,
        )
    for section in manifest["sections"]:
        chapter = budget_view(
            [r for r in rows if str(r["section_id"]) == section["section_id"]],
            section["budget_limit_minor"],
            price["currency"],
        )
        needed = (
            extra if next_section and section["section_id"] == next_section["section_id"] else 0
        )
        if chapter["over_limit"] or chapter["remaining_minor"] < needed:
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_BUDGET_INSUFFICIENT",
                "该章全部尝试的累计费用与预留已达到章额度",
                409,
                {"section_ids": [section["section_id"]]},
            )
    return rows, total


def assert_frozen_size(c, identity):
    size = fetch(
        c,
        """SELECT coalesce(sum(octet_length(convert_to(package_canonical_json(j.input_manifest),'UTF8'))),0) AS size
        FROM assistant_generation_batch_attempts a JOIN assistant_jobs j ON j.id=a.job_id WHERE a.batch_id=%s""",
        (identity,),
    )["size"]
    if size > contracts.MAX_FROZEN_BYTES:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_TOO_LARGE",
            "批次全部尝试的完整冻结输入超过容量，请减少章节或来源",
            422,
        )


def retry_blocked(row, attempt, chapter_budget, total_budget, *, latest):
    if row["resolution"] is not None:
        return {"code": "AUTHORING_GENERATION_BATCH_RESOLVED", "message": "批次已有最终处理结果"}
    if attempt["attempt"] != latest:
        return {"code": "AUTHORING_GENERATION_BATCH_ATTEMPT_CHANGED", "message": "该章已有后续尝试"}
    if attempt["state"] not in TERMINAL:
        return {
            "code": "AUTHORING_GENERATION_BATCH_RUNNING",
            "message": "原任务尚未终结，请等待或显式取消",
        }
    if (
        attempt["budget_state"] not in {"settled", "released"}
        or attempt["unresolved_call"]
        or attempt["requires_manual_reconciliation"]
        or total_budget["requires_reconciliation"]
    ):
        return {
            "code": "AUTHORING_GENERATION_BATCH_RECONCILIATION_REQUIRED",
            "message": "原任务或本批次的费用尚未核清，不能新尝试",
        }
    if attempt["state"] == "succeeded" and attempt["publication_state"] not in {"stale", "failed"}:
        return {
            "code": "AUTHORING_GENERATION_BATCH_NOT_FAILED",
            "message": "该章已成功或正等待候选发布，不属于失败重试",
        }
    if attempt["attempt"] >= contracts.MAX_ATTEMPTS:
        return {
            "code": "AUTHORING_GENERATION_BATCH_ATTEMPT_LIMIT",
            "message": "该章已达到显式尝试次数上限",
        }
    section = next(
        s for s in row["manifest"]["sections"] if s["section_id"] == str(attempt["section_id"])
    )
    extra = reservation_estimate(row["manifest"]["price"], section["max_tokens"])
    if (
        min(chapter_budget["remaining_minor"], total_budget["remaining_minor"]) < extra
        or total_budget["over_limit"]
        or chapter_budget["over_limit"]
    ):
        return {
            "code": "AUTHORING_GENERATION_BATCH_BUDGET_INSUFFICIENT",
            "message": "累计额度不足以完整预留下一次尝试",
        }
    return None


def attempt_view(row, item, chapter_budget, total_budget, latest):
    blocked = retry_blocked(row, item, chapter_budget, total_budget, latest=latest)
    return clean(
        {
            "attempt": item["attempt"],
            "job_id": item["job_id"],
            "operation_id": item["operation_id"],
            "writing_plan_id": item["writing_plan_id"],
            "created_at": item["created_at"],
            "created_by": item["created_by"],
            "state": item["state"],
            "publication_state": item["publication_state"],
            "action_id": item["action_id"],
            "candidate_digest": item["candidate_digest"],
            "candidate_url": f"{contracts.BASE.format(bid_id=row['bid_id'], draft_id=row['draft_id'])}/{row['id']}/candidates/{item['action_id']}"
            if item["action_id"]
            else None,
            "error_code": item["error_code"],
            "budget_state": item["budget_state"],
            "reserved_minor": amount(item["reserved_minor"]),
            "charged_minor": amount(item["charged_minor"])
            if item["charged_minor"] is not None
            else None,
            "requires_reconciliation": bool(
                item["unresolved_call"]
                or item["requires_manual_reconciliation"]
                or item["budget_state"] in {"sent", "unknown"}
            ),
            "retry_allowed": blocked is None,
            "retry_blocked_reason": blocked,
        }
    )


def summary(row, rows):
    latest = {}
    for item in rows:
        latest[str(item["section_id"])] = item
    manifest = row["manifest"]
    return clean(
        {
            "batch_id": row["id"],
            "bid_id": row["bid_id"],
            "draft_id": row["draft_id"],
            "batch_digest": row["digest"],
            "base_draft_revision": row["base_draft_revision"],
            "state": row["resolution"]["batch_state"] if row["resolution"] else "open",
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "section_count": manifest.get("section_count", len(manifest.get("sections", []))),
            "ready_count": sum(
                v["publication_state"] == "published"
                and v["action_state"] == "pending"
                and v["expires_at"] > now()
                for v in latest.values()
            ),
            "failed_count": sum(
                v["state"] in {"failed", "cancelled"}
                or v["publication_state"] in {"stale", "failed"}
                for v in latest.values()
            ),
            "running_count": sum(
                v["state"] not in TERMINAL
                or (v["state"] == "succeeded" and v["publication_state"] == "pending")
                for v in latest.values()
            ),
            "budget": budget_view(
                rows, manifest["request"]["total_limit_minor"], manifest["price"]["currency"]
            ),
        }
    )


def load(c, bid, draft, identity):
    require_schema(c)
    row = row_for(c, bid, draft, identity)
    rows = attempts(c, identity)
    base = summary(row, rows)
    manifest = row["manifest"]
    chapters = []
    for section in manifest["sections"]:
        records = [r for r in rows if str(r["section_id"]) == section["section_id"]]
        if not records:
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_LEDGER_INCOMPLETE", "冻结章节缺少原任务回执", 409
            )
        chapter_budget = budget_view(
            records, section["budget_limit_minor"], manifest["price"]["currency"]
        )
        latest = records[-1]["attempt"]
        public = {k: v for k, v in section.items() if k != "plan_digest"}
        chapters.append(
            public
            | {
                "current_attempt": latest,
                "budget": chapter_budget,
                "attempts": [
                    attempt_view(row, r, chapter_budget, base["budget"], latest) for r in records
                ],
            }
        )
    value = base | {
        "protocol": PROTOCOL,
        "generation_mode": contracts.MODE,
        **{
            k: v
            for k, v in manifest["target"].items()
            if k not in {"base_draft_revision", "context"}
        },
        "price": manifest["price"],
        "reason": manifest["request"]["reason"],
        "sections": chapters,
        "preparation": manifest["preparation"],
        "resolution": row["resolution"],
        "current_validity": "rechecked_on_retry_and_apply",
        "requires_explicit_selection": True,
        "atomic_apply": True,
    }
    return value | {"etag": '"' + sha(value) + '"'}


def history(c, bid, draft, cursor=None, limit=20):
    require_schema(c)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise DomainError("AUTHORING_GENERATION_BATCH_INVALID", "历史分页大小须在1至50之间", 422)
    fetch(c, "SELECT id FROM drafts WHERE id=%s AND bid_id=%s", (draft, bid))
    cursor_id = None
    cursor_at = None
    if cursor:
        try:
            cursor_id = UUID(cursor)
        except (ValueError, TypeError, AttributeError):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_CURSOR_INVALID", "历史游标不合法", 422
            ) from None
        previous = fetch(
            c,
            "SELECT created_at FROM assistant_generation_batches WHERE bid_id=%s AND draft_id=%s AND id=%s",
            (bid, draft, cursor_id),
        )
        cursor_at = previous["created_at"]
    # History never loads source text, frozen plans or complete model candidates.
    rows = c.execute(
        """SELECT b.id,b.bid_id,b.draft_id,b.digest,b.base_draft_revision,b.created_at,b.created_by,
        jsonb_build_object('section_count',jsonb_array_length(b.manifest->'sections'),'request',jsonb_build_object('total_limit_minor',b.manifest#>'{request,total_limit_minor}'),
        'price',jsonb_build_object('currency',b.manifest#>'{price,currency}')) AS manifest,
        CASE WHEN r.batch_id IS NULL THEN NULL ELSE jsonb_build_object('batch_state',r.result->'batch_state') END AS resolution
        FROM assistant_generation_batches b LEFT JOIN assistant_generation_batch_resolutions r ON r.batch_id=b.id
        WHERE b.bid_id=%s AND b.draft_id=%s AND (%s::uuid IS NULL OR (b.created_at,b.id)<(%s,%s::uuid))
        ORDER BY b.created_at DESC,b.id DESC LIMIT %s""",
        (bid, draft, cursor_id, cursor_at, cursor_id, limit + 1),
    ).fetchall()
    return {
        "bid_id": str(bid),
        "draft_id": str(draft),
        "items": [summary(r, attempts(c, r["id"])) for r in rows[:limit]],
        "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
        "has_more": len(rows) > limit,
    }


def retry(c, bid, draft, identity, actor, key, body, condition):
    contracts.validate("AuthoringGenerationBatchRetryRequest", body)
    with c.transaction():
        command = start(c, bid, draft, actor, key, body, condition, RETRY_KIND, identity)
        if command.replay:
            return command.replay, True
        require_schema(c)
        row = row_for(c, bid, draft, identity)
        assert_open(row, body["batch_digest"])
        assert_target(c, bid, draft, row, condition)
        context.lock_scope(c, [bid])
        budget.lock(c)
        rows, total = assert_budget(c, row)
        section = next(
            (s for s in row["manifest"]["sections"] if s["section_id"] == body["section_id"]), None
        )
        if section is None:
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_SECTION_UNAVAILABLE", "章节不属于原批次", 409
            )
        records = [r for r in rows if str(r["section_id"]) == section["section_id"]]
        previous = records[-1]
        if (
            previous["attempt"] != body["previous_attempt"]
            or str(previous["job_id"]) != body["previous_job_id"]
        ):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_ATTEMPT_CHANGED",
                "重试所指任务不是该章最后一次尝试",
                409,
            )
        chapter_budget = budget_view(
            records, section["budget_limit_minor"], row["manifest"]["price"]["currency"]
        )
        blocked = retry_blocked(row, previous, chapter_budget, total, latest=previous["attempt"])
        if blocked:
            raise DomainError(blocked["code"], blocked["message"], 409)
        if current_price(c) != row["manifest"]["price"]:
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_PRICE_CHANGED",
                "冻结价格已不再适用，请建立新批次确认预算",
                409,
            )
        assert_budget(c, row, next_section=section)
        job_id, _ = record_attempt(
            c,
            bid,
            draft,
            identity,
            actor,
            command,
            section,
            previous["attempt"] + 1,
            row["manifest"]["price"],
            previous_job=previous["job_id"],
        )
        assert_frozen_size(c, identity)
        assert_budget(c, row)
        result = receipt(
            row,
            binding(command, actor, key, body, condition, bid, draft),
            "retried",
            jobs_created=[job_id],
        )
        audit(
            c,
            actor,
            bid,
            "authoring.generation_batch_retried",
            {
                "batch_id": str(identity),
                "section_id": section["section_id"],
                "previous_job_id": str(previous["job_id"]),
                "job_id": job_id,
            },
            command.id,
        )
        return command.finish(
            result, 200, {"ETag": row["manifest"]["target"]["base_draft_etag"]}
        ), False


def candidate(c, bid, draft, identity, action):
    from packages.authoring import batch_patches

    require_schema(c)
    row = row_for(c, bid, draft, identity)
    return batch_patches.preview(c, bid, draft, row, action)


def close_actions(c, row, actor, command, result, selected):
    selected_ids = {s["action_id"] for s in selected}
    rows = attempts(c, row["id"])
    for attempt in rows:
        if attempt["action_id"] is not None and attempt["action_state"] == "pending":
            chosen = str(attempt["action_id"]) in selected_ids
            state = "executed" if chosen else "rejected"
            c.execute(
                "INSERT INTO action_consumptions(action_id,command_id,consumed_by,result) VALUES(%s,%s,%s,%s)",
                (
                    attempt["action_id"],
                    command.id,
                    actor,
                    Jsonb(
                        result
                        | {
                            "section_id": str(attempt["section_id"]),
                            "selected": chosen,
                            "assistant_resolution": {"state": state, "http_status": 200},
                        }
                    ),
                ),
            )
            c.execute(
                "UPDATE assistant_action_links SET state=%s,revision=revision+1,resolved_by=%s,resolved_at=clock_timestamp() WHERE action_id=%s AND state='pending'",
                (state, actor, attempt["action_id"]),
            )
        if attempt["state"] not in TERMINAL:
            c.execute(
                "UPDATE operations SET state='cancel_requested',cancel_requested_at=coalesce(cancel_requested_at,clock_timestamp()) WHERE id=%s AND state IN ('queued','running','cancel_requested')",
                (attempt["operation_id"],),
            )


def resolve(c, bid, draft, identity, actor, key, body, condition):
    from packages.authoring import batch_patches

    contracts.validate("AuthoringGenerationBatchResolveRequest", body)
    selected = body["selections"]
    if (body["decision"] == "apply" and not selected) or (
        body["decision"] == "reject" and selected
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_SELECTION_INVALID",
            "应用须明确选择成功章节，拒绝须保持空选择",
            422,
        )
    if len({s["section_id"] for s in selected}) != len(selected) or len(
        {s["action_id"] for s in selected}
    ) != len(selected):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_SELECTION_INVALID", "同一章节或候选不能重复选择", 422
        )
    with c.transaction():
        command = start(
            c,
            bid,
            draft,
            actor,
            key,
            body,
            condition,
            RESOLVE_KIND,
            identity,
            work=body["decision"] == "apply",
        )
        if command.replay:
            return command.replay, True
        require_schema(c)
        row = row_for(c, bid, draft, identity)
        assert_open(row, body["batch_digest"])
        saved = None
        if body["decision"] == "apply":
            assert_target(c, bid, draft, row, condition)
            context.lock_scope(c, [bid])
            budget.lock(c)
            rows, total = assert_budget(c, row)
            if any(
                r["state"] not in TERMINAL
                or (r["state"] == "succeeded" and r["publication_state"] == "pending")
                for r in rows
            ):
                raise DomainError(
                    "AUTHORING_GENERATION_BATCH_RUNNING",
                    "请等待所有章节任务终结并完成候选整理后，再统一确认正文",
                    409,
                )
            if total["requires_reconciliation"] or any(
                r["budget_state"] not in {"settled", "released"} for r in rows
            ):
                raise DomainError(
                    "AUTHORING_GENERATION_BATCH_RECONCILIATION_REQUIRED",
                    "批次费用尚未核清，候选已保留，尚未应用正文",
                    409,
                )
            changes = batch_patches.changes_for_apply(c, bid, draft, row, selected)
            saved = repository.save_draft(
                c,
                bid,
                draft,
                actor,
                {"base_draft_revision": row["base_draft_revision"], "changes": changes},
                condition,
            )
        kind = "applied" if body["decision"] == "apply" else "rejected"
        result = receipt(
            row,
            binding(command, actor, key, body, condition, bid, draft),
            kind,
            selected=[s["section_id"] for s in selected],
            saved=saved,
        )
        close_actions(c, row, actor, command, result, selected)
        c.execute(
            "INSERT INTO assistant_generation_batch_resolutions(batch_id,bid_id,draft_id,command_id,resolved_by,decision,result,digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (identity, bid, draft, command.id, actor, body["decision"], Jsonb(result), sha(result)),
        )
        audit(
            c,
            actor,
            bid,
            "authoring.generation_batch_resolved",
            {
                "batch_id": str(identity),
                "batch_digest": row["digest"],
                "draft_id": str(draft),
                "decision": body["decision"],
            },
            command.id,
        )
        headers = {"ETag": repository.draft_etag(draft, saved["draft_revision"])} if saved else {}
        return command.finish(result, 200, headers), False
