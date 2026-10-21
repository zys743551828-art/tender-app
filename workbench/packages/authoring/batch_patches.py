"""Ledger-backed chapter candidates consumed only by one explicit batch save.

Candidate publication performs no model call and never edits the draft. Preview
is a read-only reconstruction of exact frozen inputs and checked model patches.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from uuid import UUID

from psycopg.types.json import Jsonb

from packages.assistant import context, generation_batches, intent_identity, jobs
from packages.authoring import repository, section_patch_set, section_sources
from packages.authoring.patches import proposal_context
from packages.domain.runtime import DomainError, clean, fetch, now, sha, uid


def checked_job(c, bid, batch, section, number, job_id, writing_plan_id):
    attempt = fetch(
        c,
        """SELECT * FROM assistant_generation_batch_attempts
        WHERE batch_id=%s AND bid_id=%s AND draft_id=%s AND section_id=%s AND attempt=%s
        AND job_id=%s AND writing_plan_id=%s""",
        (batch["id"], bid, batch["draft_id"], section, number, job_id, writing_plan_id),
    )
    job = jobs.job(c, job_id)
    frozen = job["input_manifest"]
    expected = {"batch_id": str(batch["id"]), "section_id": str(section), "attempt": number}
    plan_row = fetch(
        c, "SELECT * FROM writing_plans WHERE id=%s AND bid_id=%s", (writing_plan_id, bid)
    )
    selected = next(
        (s for s in batch["manifest"]["sections"] if s["section_id"] == str(section)), None
    )
    if (
        selected is None
        or job["scope"] != "project"
        or job["kind"] != "authoring"
        or job["bid_id"] != bid
        or job["writing_plan_id"] != writing_plan_id
        or frozen.get("generation_mode") != section_patch_set.MODE
        or frozen.get("batch_context") != expected
        or frozen.get("writing_plan_id") != str(writing_plan_id)
        or frozen["request"] != generation_batches.generation_request(selected)
        or plan_row["section_id"] != section
        or plan_row["base_section_revision"] != selected["base_section_revision"]
        or plan_row["plan"] != frozen["plan"]
        or frozen["plan"]["section_digest"] != selected["before_digest"]
        or frozen["plan"]["patch_scope"]
        != section_patch_set.freeze_scope(
            frozen["plan"]["original_content"], selected["selected_node_ids"]
        )
        or sha({"plan": frozen["plan"], "project_memory": frozen["project_memory"]})
        != selected["plan_digest"]
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_CANDIDATE_CHANGED",
            "候选与冻结的章节、范围或任务身份不一致",
            409,
        )
    return attempt, job, selected


def assert_inputs(c, bid, draft, section, job):
    frozen = job["input_manifest"]
    plan = frozen["plan"]
    if proposal_context(c, bid) != plan["context"]:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_CONTEXT_CHANGED", "项目事实或要求与冻结输入不同", 409
        )
    context.assert_generation_context(c, bid, frozen["project_memory"])
    intent_identity.revalidate(
        c,
        frozen["logical_intent"]["target"],
        job["actor_id"],
        frozen["request"],
        bid,
        generation=True,
    )
    checked = deepcopy(plan["original_content"])
    checked["attrs"]["source_refs"] = list(
        {
            sha(ref): ref
            for ref in checked["attrs"]["source_refs"]
            + [b["source_ref"] for b in plan["source_blocks"]]
        }.values()
    )
    repository.assert_sources(c, bid, checked)
    if section_sources.authority(c, bid, draft, section, checked) != plan["authority_manifest"]:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_SOURCE_CHANGED", "原生成输入的来源或祖先效力已经变化", 409
        )


def accept_generated_patch_set(c, bid, writing_plan_id, canonical, batch_context, *, job_id):
    try:
        identity = UUID(batch_context["batch_id"])
        section = UUID(batch_context["section_id"])
        number = batch_context["attempt"]
        if set(batch_context) != {"batch_id", "section_id", "attempt"} or type(number) is not int:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_CANDIDATE_CHANGED", "批次任务身份不完整", 409
        ) from None
    scope = fetch(
        c,
        "SELECT draft_id FROM assistant_generation_batches WHERE id=%s AND bid_id=%s",
        (identity, bid),
    )
    draft = scope["draft_id"]
    row = generation_batches.row_for(c, bid, draft, identity)
    generation_batches.assert_open(row)
    generation_batches.assert_target(
        c, bid, draft, row, row["manifest"]["target"]["base_draft_etag"]
    )
    _, job, selected = checked_job(c, bid, row, section, number, job_id, writing_plan_id)
    latest = fetch(
        c,
        "SELECT max(attempt) AS attempt FROM assistant_generation_batch_attempts WHERE batch_id=%s AND section_id=%s",
        (identity, section),
    )
    if latest["attempt"] != number:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_ATTEMPT_CHANGED", "该任务已有后续尝试，不能发布旧候选", 409
        )
    output = fetch(
        c,
        """SELECT out.payload,out.digest,op.state
        FROM assistant_outputs out JOIN assistant_jobs j ON j.id=out.job_id
        JOIN operations op ON op.id=j.operation_id WHERE j.id=%s""",
        (job_id,),
    )
    if (
        output["state"] != "succeeded"
        or output["payload"] != canonical
        or sha(canonical) != output["digest"]
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_OUTPUT_UNVERIFIED", "候选不是该成功任务的精确账本输出", 409
        )
    assert_inputs(c, bid, draft, section, job)
    preview = section_patch_set.materialize(
        job["input_manifest"]["plan"], str(writing_plan_id), canonical
    )
    repository.assert_sources(c, bid, preview["after"])
    payload = {
        "kind": "authoring_patch_set",
        "batch_context": deepcopy(batch_context),
        "batch_digest": row["digest"],
        "job_id": str(job_id),
        "writing_plan_id": str(writing_plan_id),
        "section_id": str(section),
        "draft_id": str(draft),
        "base_section_revision": selected["base_section_revision"],
        "candidate": deepcopy(canonical),
        "context": proposal_context(c, bid),
        "authority_manifest": section_sources.authority(c, bid, draft, section, preview["after"]),
        "before_section_digest": selected["before_digest"],
        "schema_digest": preview["schema_digest"],
    }
    action = uid()
    c.execute(
        "INSERT INTO proposed_actions(id,bid_id,base_revision,request_digest,expires_at,payload) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            action,
            bid,
            row["base_draft_revision"],
            sha(payload),
            now() + timedelta(hours=2),
            Jsonb(payload),
        ),
    )
    return {
        "action_id": str(action),
        "candidate_digest": sha(payload),
        "base_draft_revision": row["base_draft_revision"],
        "before": preview["before"],
        "after": preview["after"],
        "expires_in_seconds": 7200,
    }


def checked_candidate(c, bid, draft, batch, action):
    value = fetch(
        c,
        """SELECT a.*,l.job_id,l.state AS action_state,l.created_at,
        p.state AS publication_state,t.section_id,t.attempt,t.writing_plan_id
        FROM proposed_actions a JOIN assistant_action_links l ON l.action_id=a.id
        JOIN assistant_publications p ON p.action_id=a.id AND p.job_id=l.job_id
        JOIN assistant_generation_batch_attempts t ON t.job_id=l.job_id
        WHERE a.id=%s AND a.bid_id=%s AND t.batch_id=%s AND t.bid_id=%s AND t.draft_id=%s""",
        (action, bid, batch["id"], bid, draft),
    )
    payload = value["payload"]
    _, job, selected = checked_job(
        c,
        bid,
        batch,
        value["section_id"],
        value["attempt"],
        value["job_id"],
        value["writing_plan_id"],
    )
    if (
        sha(payload) != value["request_digest"]
        or payload.get("kind") != "authoring_patch_set"
        or payload.get("batch_digest") != batch["digest"]
        or value["base_revision"] != batch["base_draft_revision"]
        or payload.get("draft_id") != str(draft)
        or payload.get("job_id") != str(value["job_id"])
        or payload.get("writing_plan_id") != str(value["writing_plan_id"])
        or payload.get("section_id") != str(value["section_id"])
        or payload.get("batch_context") != job["input_manifest"]["batch_context"]
        or payload.get("base_section_revision") != selected["base_section_revision"]
        or payload.get("before_section_digest") != selected["before_digest"]
        or value["publication_state"] != "published"
    ):
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_CANDIDATE_CHANGED", "候选的任务和批次绑定不一致", 409
        )
    output = fetch(
        c, "SELECT payload,digest FROM assistant_outputs WHERE job_id=%s", (value["job_id"],)
    )
    if output["payload"] != payload["candidate"] or sha(output["payload"]) != output["digest"]:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_OUTPUT_UNVERIFIED", "候选与实际任务输出不同", 409
        )
    content = section_patch_set.materialize(
        job["input_manifest"]["plan"], str(value["writing_plan_id"]), payload["candidate"]
    )
    if content["schema_digest"] != payload["schema_digest"]:
        raise DomainError(
            "AUTHORING_GENERATION_BATCH_CANDIDATE_CHANGED", "候选富文本协议与冻结身份不一致", 409
        )
    return value, job, content


def preview(c, bid, draft, batch, action):
    value, _, content = checked_candidate(c, bid, draft, batch, action)
    patch = value["payload"]["candidate"]
    result = clean(
        {
            "protocol": "authoring-generation-candidate/1",
            "generation_mode": section_patch_set.MODE,
            "bid_id": bid,
            "draft_id": draft,
            "batch_id": batch["id"],
            "batch_digest": batch["digest"],
            "section_id": value["section_id"],
            "attempt": value["attempt"],
            "job_id": value["job_id"],
            "writing_plan_id": value["writing_plan_id"],
            "action_id": action,
            "candidate_digest": value["request_digest"],
            "base_draft_revision": batch["base_draft_revision"],
            "base_section_revision": value["payload"]["base_section_revision"],
            "base_draft_etag": batch["manifest"]["target"]["base_draft_etag"],
            "before_digest": patch["before_digest"],
            "after_digest": patch["after_digest"],
            "scope_digest": patch["scope_digest"],
            "before": content["before"],
            "after": content["after"],
            "changes": content["changes"],
            "created_at": value["created_at"],
            "expires_at": value["expires_at"],
            "state": "expired"
            if value["action_state"] == "pending" and value["expires_at"] <= now()
            else value["action_state"],
        }
    )
    return result | {"etag": '"' + sha(result) + '"'}


def changes_for_apply(c, bid, draft, batch, selections):
    from packages.authoring.exact_sources import assert_ordinary_edit

    assert_ordinary_edit(c, bid, draft)
    changes = []
    for selected in selections:
        value, job, content = checked_candidate(c, bid, draft, batch, UUID(selected["action_id"]))
        latest = fetch(
            c,
            "SELECT max(attempt) AS attempt FROM assistant_generation_batch_attempts WHERE batch_id=%s AND section_id=%s",
            (batch["id"], value["section_id"]),
        )
        if (
            selected["section_id"] != str(value["section_id"])
            or selected["attempt"] != value["attempt"]
            or selected["job_id"] != str(value["job_id"])
            or selected["candidate_digest"] != value["request_digest"]
            or latest["attempt"] != value["attempt"]
        ):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_CANDIDATE_CHANGED", "确认项与该章最新候选不一致", 409
            )
        if (
            value["action_state"] != "pending"
            or c.execute(
                "SELECT 1 FROM action_consumptions WHERE action_id=%s", (value["id"],)
            ).fetchone()
        ):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_CANDIDATE_CONSUMED", "候选已有处理结果", 409
            )
        if value["expires_at"] <= now():
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_CANDIDATE_EXPIRED",
                "候选已过期，请核对并建立新批次",
                409,
            )
        current = fetch(
            c,
            """SELECT s.head_revision,r.digest,r.content FROM sections s
            JOIN section_revisions r ON r.section_id=s.id AND r.revision=s.head_revision
            WHERE s.id=%s AND s.bid_id=%s AND s.draft_id=%s""",
            (value["section_id"], bid, draft),
        )
        payload = value["payload"]
        if (
            current["head_revision"] != payload["base_section_revision"]
            or current["digest"] != payload["before_section_digest"]
            or current["content"] != content["before"]
        ):
            raise DomainError("SECTION_REVISION_CONFLICT", "候选基础章节已变化", 412)
        assert_inputs(c, bid, draft, value["section_id"], job)
        repository.assert_sources(c, bid, content["after"])
        if (
            section_sources.authority(c, bid, draft, value["section_id"], content["after"])
            != payload["authority_manifest"]
        ):
            raise DomainError(
                "AUTHORING_GENERATION_BATCH_SOURCE_CHANGED", "候选来源或祖先效力已经变化", 409
            )
        changes.append(
            {
                "section_id": str(value["section_id"]),
                "base_section_revision": payload["base_section_revision"],
                "schema_digest": content["schema_digest"],
                "content": content["after"],
            }
        )
    return sorted(changes, key=lambda v: v["content"]["attrs"]["ordinal"])
