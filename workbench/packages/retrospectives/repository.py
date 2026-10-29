"""Append-only retrospective packets and explicit links into the existing knowledge workflow."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from packages.contracts import package_retrospectives_api as contract
from packages.domain.review_identity import utc
from packages.domain.runtime import audit, clean, etag, fetch, match, now, sha
from packages.domain.work_access import begin
from packages.knowledge import repository as knowledge
from packages.knowledge.sources import lock_graph
from packages.retrospectives import observations, policy

FREEZE = "package-retrospective-freeze"
HANDOFF = "package-retrospective-knowledge"


def require_schema(c):
    names = ("design.package_retrospectives", "design.package_retrospective_knowledge_links")
    for name in names:
        if c.execute("SELECT to_regclass(%s) AS name", (name,)).fetchone()["name"] is None:
            policy.fail("UNAVAILABLE", "整包复盘存储尚未安装，输入可保留后重试", 503)


def load(c, bid, identity):
    require_schema(c)
    row = fetch(
        c, "SELECT * FROM design.package_retrospectives WHERE bid_id=%s AND id=%s", (bid, identity)
    )
    value = policy.check_packet(
        clean({"manifest": row["manifest"], "digest": row["digest"]}), "PackageRetrospectiveView"
    )
    m = value["manifest"]
    if (
        any(m[key] != str(row[key]) for key in ("id", "bid_id", "actor_id", "command_id"))
        or m["created_at"] != utc(clean(row["created_at"]))
        or m["preview"]["manifest"]["selection"]["submission_id"] != str(row["submission_id"])
    ):
        policy.fail("CORRUPT", "已存复盘与原实交或命令不一致", 500)
    return value


def link(c, identity):
    row = c.execute(
        "SELECT * FROM design.package_retrospective_knowledge_links WHERE retrospective_id=%s",
        (identity,),
    ).fetchone()
    if row is None:
        return None
    value = clean(
        {
            key: row[key]
            for key in (
                "retrospective_id",
                "retrospective_digest",
                "knowledge_id",
                "knowledge_version_id",
                "source_id",
                "actor_id",
                "reason",
            )
        }
    )
    value.update(
        created_at=utc(clean(row["created_at"])),
        policy_class="derived_mixed",
        knowledge_published=False,
        formal_sample_eligible=False,
    )
    if not contract.valid("PackageRetrospectiveKnowledgeLink", value):
        policy.fail("CORRUPT", "复盘知识候选关联不能核验", 500)
    return value


def preview_tag(bid, digest):
    return etag("package-retrospective-preview", bid, digest)


def saved_tag(frozen):
    return etag("package-retrospective", frozen["manifest"]["id"], frozen["digest"])


def command_view(cmd, actor, key, body, condition):
    return clean(
        {
            "command_id": cmd.id,
            "actor_id": actor,
            "idempotency_key": key,
            "request_digest": sha({"body": body, "if_match": condition}),
            "request": body,
            "if_match": condition,
        }
    )


def replay(c, cmd, actor, bid, key, body, condition, *, knowledge_link=False):
    saved = cmd.replay
    if saved is None:
        return None
    name = (
        "PackageRetrospectiveKnowledgeApplied" if knowledge_link else "PackageRetrospectiveApplied"
    )
    if (
        saved.get("status") != 201
        or not contract.valid(name, saved.get("body"))
        or saved["body"]["command"] != command_view(cmd, actor, key, body, condition)
    ):
        policy.fail("ACK_CORRUPT", "原复盘请求回执不能与同一命令核验", 500)
    value = saved["body"]
    if knowledge_link:
        if link(c, value["link"]["retrospective_id"]) != value["link"]:
            policy.fail("ACK_CORRUPT", "原知识候选关联回执不能核验", 500)
    elif load(c, bid, value["retrospective"]["manifest"]["id"]) != value["retrospective"]:
        policy.fail("ACK_CORRUPT", "原待核复盘回执不能核验", 500)
    return saved


def freeze(c, bid, actor, key, body, condition):
    contract.validate("PackageRetrospectiveRequest", body)
    policy.selection(body["selection"])
    require_schema(c)
    cmd = begin(c, actor, FREEZE, bid, key, body, condition, bid=bid)
    old = replay(c, cmd, actor, bid, key, body, condition)
    if old:
        return old, True
    lock_graph(c)
    preview = observations.observe(c, bid, body["selection"])
    match(condition, "package-retrospective-preview", bid, preview["digest"])
    if preview["digest"] != body["preview_digest"]:
        policy.fail("PREVIEW_CHANGED", "所选依据已变化，请重新预览；复盘输入仍可保留", 412)
    identity, at = uuid4(), now()
    frozen = policy.packet(
        {
            "version": "package-retrospective/1",
            "id": str(identity),
            "bid_id": bid,
            "actor_id": str(actor),
            "command_id": str(cmd.id),
            "created_at": utc(clean(at)),
            "state": "pending_review",
            "title": body["title"],
            "notes": body["notes"],
            "preview": preview,
            **policy.FLAGS,
        },
        "PackageRetrospectiveView",
    )
    c.execute(
        "INSERT INTO design.package_retrospectives(id,bid_id,submission_id,actor_id,command_id,manifest,digest,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            identity,
            bid,
            body["selection"]["submission_id"],
            actor,
            cmd.id,
            Jsonb(frozen["manifest"]),
            frozen["digest"],
            at,
        ),
    )
    audit(
        c,
        actor,
        bid,
        "package.retrospective_frozen",
        {
            "retrospective_id": identity,
            "digest": frozen["digest"],
            "submission_id": body["selection"]["submission_id"],
        },
        cmd.id,
    )
    result = {"retrospective": frozen, "command": command_view(cmd, actor, key, body, condition)}
    return cmd.finish(result, 201, {"ETag": saved_tag(frozen)}), False


def origin(frozen, source):
    return {
        "retrospective_id": frozen["manifest"]["id"],
        "retrospective_digest": frozen["digest"],
        "preview_digest": frozen["manifest"]["preview"]["digest"],
        "source_id": str(source),
    }


def handoff(c, bid, identity, actor, key, body, condition):
    contract.validate("PackageRetrospectiveKnowledgeRequest", body)
    require_schema(c)
    cmd = begin(c, actor, HANDOFF, identity, key, body, condition, bid=bid)
    old = replay(c, cmd, actor, bid, key, body, condition, knowledge_link=True)
    if old:
        return old, True
    lock_graph(c)
    frozen = load(c, bid, identity)
    match(condition, "package-retrospective", identity, frozen["digest"])
    if body["retrospective_digest"] != frozen["digest"]:
        policy.fail("DIGEST_MISMATCH", "请核对当前明确选择的复盘摘要", 412)
    if link(c, identity):
        policy.fail("KNOWLEDGE_EXISTS", "该复盘已建立知识候选，可从原关联继续维护", 409)
    current = observations.current(c, frozen)
    if not current["unchanged"]:
        policy.fail(
            "SOURCE_CHANGED",
            "原复盘依据已变化或来源不可用，请重新预览并建立新复盘；历史记录保留",
            409,
        )
    m, item, source, at = frozen["manifest"], uuid4(), uuid4(), now()
    preview = m["preview"]["manifest"]
    c.execute(
        "INSERT INTO retrieval.source_nodes(id,kind,policy_class,known_at,digest) VALUES(%s,'summary','post_outcome',%s,%s)",
        (source, at, frozen["digest"]),
    )
    # Published here means the immutable retrospective record exists. The new
    # knowledge version remains candidate and cannot be retrieved as published.
    c.execute(
        "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',%s)",
        (source, at),
    )
    for parent in preview["source_ids"]:
        c.execute(
            "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
            (source, parent),
        )
    c.execute(
        "INSERT INTO retrieval.knowledge_items(id,title,revision) VALUES(%s,%s,1)",
        (item, m["title"]),
    )
    metadata = {
        "readiness": "needs_applicability",
        "title": m["title"],
        "scope": "整包事后复盘；仅作为待核历史参考",
        "origin_bid_id": bid,
        "declared_source_version_ids": [d["id"] for d in preview["documents"]],
        "source_refs": [],
        "originals": [],
        "retrospective_origin": origin(frozen, source),
    }
    version = knowledge.insert_version(
        c,
        item,
        1,
        actor,
        policy.knowledge_content(frozen),
        ["retrospective"],
        metadata,
        [source],
        "derived_mixed",
        at,
    )
    c.execute(
        "INSERT INTO design.package_retrospective_knowledge_links(retrospective_id,bid_id,retrospective_digest,knowledge_id,knowledge_version_id,source_id,actor_id,command_id,reason,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (identity, bid, frozen["digest"], item, version, source, actor, cmd.id, body["reason"], at),
    )
    audit(
        c,
        actor,
        bid,
        "knowledge.candidate_created",
        {"knowledge_id": item, "version_id": version, "retrospective_id": identity},
        cmd.id,
    )
    audit(
        c,
        actor,
        bid,
        "package.retrospective_knowledge_candidate_created",
        {"retrospective_id": identity, "knowledge_id": item, "version_id": version},
        cmd.id,
    )
    value = link(c, identity)
    return cmd.finish(
        {"link": value, "command": command_view(cmd, actor, key, body, condition)},
        201,
        {"ETag": saved_tag(frozen)},
    ), False


def detail(c, bid, identity):
    frozen = load(c, bid, identity)
    return {
        "retrospective": frozen,
        "current": observations.current(c, frozen),
        "knowledge_link": link(c, identity),
    }


def directory(c, bid, limit, offset):
    require_schema(c)
    fetch(c, "SELECT id FROM design.bids WHERE id=%s", (bid,))
    rows = clean(
        c.execute(
            "SELECT id,manifest->>'title' AS title,submission_id,created_at,digest FROM design.package_retrospectives WHERE bid_id=%s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
            (bid, limit + 1, offset),
        ).fetchall()
    )
    return {
        "bid_id": bid,
        "items": rows[:limit],
        "next_offset": offset + limit if len(rows) > limit else None,
    }
