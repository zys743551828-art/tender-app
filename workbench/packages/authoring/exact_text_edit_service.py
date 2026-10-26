"""Explicit manual edits: replay first, original I/O outside locks, final CAS and provenance."""

from uuid import UUID

from packages.authoring import exact_builds, exact_sources, exact_text_edits, repository
from packages.authoring.exact_text_edit_contracts import (
    AuthoringExactTextEditRequest,
    AuthoringExactTextEditResult,
)
from packages.domain.runtime import DomainError, audit, clean, connection, fetch, match, sha
from packages.domain.work_access import begin


def capabilities(c):
    ready = exact_text_edits.available(c)
    return {
        "protocol": "authoring-exact-text-edit-capabilities/1",
        "available": ready,
        "supported_content": "plain_text_stable_node",
        "preserves_source_refs": True,
        "preserves_rule_ids": True,
        "ordinary_edit_available": False,
        "blocking_reasons": [] if ready else ["AUTHORING_EXACT_TEXT_EDIT_NOT_CONFIGURED"],
    }


def _scope(c, bid, draft):
    return fetch(c, "SELECT * FROM design.drafts WHERE bid_id=%s AND id=%s", (bid, draft))


def _replay(c, bid, draft, actor, key, body, condition):
    _scope(c, bid, draft)
    row = c.execute(
        "SELECT * FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, exact_text_edits.KIND, draft, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": condition}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "原文字修订请求的内容或条件不能改变", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "原文字修订尚未取得完整回执", 409)
    stored = row["response"]
    value = stored.get("body", {})
    AuthoringExactTextEditResult.model_validate(value)
    q = exact_sources.load(c, bid, UUID(value["section_revision_id"]))
    if (
        stored.get("status") != 200
        or value["bid_id"] != str(bid)
        or value["draft_id"] != str(draft)
        or value["parent_section_revision_id"] != body["section_revision_id"]
        or value["draft_revision"] != body["base_draft_revision"] + 1
        or value["qualification"] != q
        or q["manifest"]["origin"]["command_id"] != str(row["id"])
        or q["manifest"]["origin"]["actor_id"] != str(actor)
        or stored.get("headers", {}).get("ETag")
        != repository.draft_etag(draft, value["draft_revision"])
    ):
        exact_text_edits.rejected("原文字修订回执与真实保存关系不一致")
    return stored


def _capture(c, bid, draft, body, condition):
    exact_text_edits.require_available(c)
    row = repository.lock_draft(c, bid, draft)
    match(condition, "draft", draft, row["revision"])
    if body["base_draft_revision"] != row["revision"]:
        raise DomainError("DRAFT_REVISION_CONFLICT", "草稿已更新，请保留文字并核对新基准", 412)
    q = exact_sources.assert_current(c, bid, UUID(body["section_revision_id"]))
    p = q["manifest"]
    if p["draft_id"] != str(draft):
        exact_text_edits.rejected()
    current = fetch(
        c,
        "SELECT * FROM design.sections WHERE id=%s AND bid_id=%s AND draft_id=%s",
        (p["section_id"], bid, draft),
    )
    if current["head_revision"] != p["section_revision"]:
        raise DomainError("SECTION_REVISION_CONFLICT", "所选章节已经更新，未改写旧修订", 412)
    snapshot = fetch(
        c,
        "SELECT * FROM design.draft_snapshots WHERE bid_id=%s AND draft_id=%s AND revision=%s",
        (bid, draft, row["revision"]),
    )
    original = fetch(
        c, "SELECT * FROM design.section_revisions WHERE id=%s", (p["section_revision_id"],)
    )
    content = exact_text_edits.materialize(original["content"], body)
    saved = repository.snapshot_content(c, bid, snapshot["id"])
    packet = exact_builds.capture(c, bid, saved, current=True)
    if packet is None or not any(
        item["section_revision_id"] == p["section_revision_id"]
        for item in saved["authoring_exact_sections"]["sections"]
    ):
        exact_text_edits.rejected()
    return {
        "qualification": q,
        "content": content,
        "packet": packet,
        "before_action": {
            "request": body,
            "base_snapshot_id": str(snapshot["id"]),
            "base_snapshot_digest": snapshot["digest"],
        },
    }


def save(actor, bid, draft, key, condition, request, *, final_auth):
    body = clean(AuthoringExactTextEditRequest.model_validate(request).model_dump(mode="json"))
    if not key or not isinstance(key, str) or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的文字修订操作键", 428)
    actor, bid, draft = UUID(str(actor)), UUID(str(bid)), UUID(str(draft))
    with exact_sources.errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = _replay(c, bid, draft, actor, key, body, condition)
        if old is not None:
            return old, True
    try:
        with exact_sources.errors(), connection() as c:
            prepared = _capture(c, bid, draft, body, condition)
    except DomainError:
        # An identical in-flight command can commit between the first replay
        # read and the locked capture. Recover its original acknowledgement;
        # never replace the request's base with the now-current draft.
        with exact_sources.errors(), connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            old = _replay(c, bid, draft, actor, key, body, condition)
            if old is not None:
                return old, True
        raise
    # Neither connection nor source/draft locks are held during S3 reads.
    exact_builds.verify_originals(prepared["packet"])
    with exact_sources.errors(), connection() as c:
        _scope(c, bid, draft)
        command = begin(c, actor, exact_text_edits.KIND, draft, key, body, condition, bid=bid)
        if command.replay:
            return _replay(c, bid, draft, actor, key, body, condition), True
        current = _capture(c, bid, draft, body, condition)
        if current != prepared:
            exact_text_edits.rejected("原件核验期间的来源或草稿已变化，未保存文字修订")
        verified_actor = final_auth()
        if (
            UUID(
                str(
                    verified_actor["member_id"]
                    if isinstance(verified_actor, dict)
                    else verified_actor
                )
            )
            != actor
        ):
            raise DomainError(
                "AUTHORING_EXACT_ACTOR_CHANGED", "保存期间操作者已变化，未保存文字修订", 403
            )
        q = current["qualification"]
        p = q["manifest"]
        admission = exact_text_edits.ExactManualEdit(
            command.id,
            actor,
            condition,
            current["before_action"],
            UUID(p["id"]),
            q["digest"],
        )
        saved = repository.save_draft(
            c,
            bid,
            draft,
            actor,
            {
                "base_draft_revision": body["base_draft_revision"],
                "changes": [
                    {
                        "section_id": p["section_id"],
                        "base_section_revision": p["section_revision"],
                        "schema_digest": p["schema_digest"],
                        "content": current["content"],
                    }
                ],
            },
            condition,
            exact_admission=admission,
        )
        derived = fetch(
            c,
            "SELECT manifest,digest FROM design.authoring_exact_manual_revisions WHERE id=%s",
            (admission.qualification_id,),
        )
        result = clean(
            {
                "protocol": "authoring-exact-text-edit-result/1",
                "bid_id": bid,
                **saved,
                "parent_section_revision_id": p["section_revision_id"],
                "section_revision_id": admission.section_revision_id,
                "section_digest": sha(current["content"]),
                "qualification": derived,
            }
        )
        AuthoringExactTextEditResult.model_validate(result)
        audit(
            c,
            actor,
            bid,
            "authoring.exact_text_edited",
            {
                "qualification_id": admission.qualification_id,
                "qualification_digest": derived["digest"],
                "section_revision_id": admission.section_revision_id,
                "snapshot_id": saved["snapshot_id"],
                "snapshot_digest": saved["snapshot_digest"],
            },
            command.id,
        )
        stored = command.finish(
            result, 200, {"ETag": repository.draft_etag(draft, saved["draft_revision"])}
        )
    return stored, False
