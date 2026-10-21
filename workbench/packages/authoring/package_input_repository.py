"""Optional schema and append-only input reads; never execution readiness."""

import json

from packages.authoring import package_admission as admission
from packages.domain.runtime import DomainError, fetch, sha
from packages.identity import pagination

KIND = "authoring-package-input-save"
WITHDRAW = "authoring-package-fact-withdraw"
TABLES = ("authoring_package_inputs", "authoring_package_fact_scopes")


def available(c):
    return all(
        c.execute("SELECT to_regclass(%s) IS NOT NULL AS exists", ("design." + table,)).fetchone()[
            "exists"
        ]
        and c.execute(
            "SELECT has_table_privilege(current_user,%s,'SELECT') AS allowed", ("design." + table,)
        ).fetchone()["allowed"]
        for table in TABLES
    )


def require_schema(c):
    if not available(c):
        raise DomainError(
            "AUTHORING_PACKAGE_INPUT_NOT_CONFIGURED", "固定整包编写输入尚未配置独立存储", 503
        )


def capabilities(c):
    installed = available(c)
    return {
        "protocol": "package-authoring-input-capabilities/1",
        "capture_available": installed,
        "generation_available": False,
        "publication_available": False,
        "apply_available": False,
        "build_available": False,
        "automatic_input_selection": False,
        "supported_target": "plain_text_stable_node",
        "target_relation": "draft_using_package_context",
        "context_limit_bytes": admission.MAX_CONTEXT_BYTES,
        "blocking_reasons": ["AUTHORING_PACKAGE_EXECUTOR_NOT_READY"]
        if installed
        else ["AUTHORING_PACKAGE_INPUT_NOT_CONFIGURED"],
    }


def replay(c, actor, bid, key, body, *, kind=KIND, target=None):
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, kind, target or bid, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同的固定输入", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "原操作尚未完成", 409)
    return row["response"]


def load(c, bid, identity):
    require_schema(c)
    row = fetch(
        c,
        "SELECT * FROM design.authoring_package_inputs WHERE bid_id=%s AND id=%s",
        (bid, identity),
    )
    manifest = row["manifest"]
    if (
        sha(manifest) != row["digest"]
        or sha(row["context_text"].encode()) != row["context_digest"]
        or manifest["context_digest"] != row["context_digest"]
        or manifest["id"] != str(identity)
        or manifest["bid_id"] != str(bid)
    ):
        raise DomainError("AUTHORING_PACKAGE_INPUT_CORRUPT", "固定输入记录摘要或归属不一致", 409)
    context = json.loads(row["context_text"])
    if (
        context["request"] != manifest["selection"]
        or context["bid_id"] != str(bid)
        or context["method_digest"] != manifest["method_digest"]
    ):
        raise DomainError("AUTHORING_PACKAGE_INPUT_CORRUPT", "固定输入内容与清单不对应", 409)
    return row


def view(row):
    return {"manifest": row["manifest"], "digest": row["digest"]}


def directory(c, bid, *, limit=20, cursor=None):
    require_schema(c)
    fetch(c, "SELECT id FROM design.bids WHERE id=%s", (bid,))
    scope = sha({"directory": "authoring-package-inputs/1", "bid_id": str(bid)})
    after = pagination.decode(cursor, scope)
    if after and after[0] != "":
        raise DomainError("INVALID_CURSOR", "游标不属于固定编写输入目录", 422)
    last = after[-1] if after else None
    rows = c.execute(
        "SELECT id FROM design.authoring_package_inputs WHERE bid_id=%s AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
        (bid, last, last, limit + 1),
    ).fetchall()
    items = [view(load(c, bid, row["id"])) for row in rows[:limit]]
    return {
        "items": items,
        "has_more": len(rows) > limit,
        "next_cursor": pagination.encode(scope, ["", items[-1]["manifest"]["id"]])
        if len(rows) > limit
        else None,
    }


def declarations_match(c, row):
    for expected in row["manifest"]["fact_declarations"]:
        current = c.execute(
            "SELECT manifest,digest FROM design.authoring_package_fact_scopes WHERE bid_id=%s AND input_id=%s AND fact_id=%s ORDER BY revision DESC LIMIT 1",
            (row["bid_id"], row["id"], expected["manifest"]["fact_id"]),
        ).fetchone()
        if (
            not current
            or current["manifest"] != expected["manifest"]
            or current["digest"] != expected["digest"]
        ):
            raise DomainError(
                "AUTHORING_PACKAGE_FACT_DECLARATION_WITHDRAWN", "本输入的事实用途声明已撤回", 409
            )


def public_context(row):
    value = json.loads(row["context_text"])
    for document in value["documents"]:
        document.pop("object_key", None)
    # Native extraction manifests contain only original identities, not provider credentials.
    return {
        "input_id": str(row["id"]),
        "input_digest": row["digest"],
        "stored_context_digest": row["context_digest"],
        "context": value,
        "redacted_fields": ["documents[*].object_key"],
        "original_bytes_reverified": False,
    }
