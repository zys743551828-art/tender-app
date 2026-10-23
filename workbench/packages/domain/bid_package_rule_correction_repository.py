"""Exact inventory correction archives and evidence; no object IO or current-material lookup."""

import json
from copy import deepcopy

from psycopg.types.json import Jsonb

from packages.domain import bid_package_repository as packages
from packages.domain.bid_package_service import view
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError, clean, etag, sha
from packages.identity import pagination

KIND = "package-rule-correction-apply"
EVENT = "package.rules_corrected"
MAX_CHAIN_BYTES = 64 * 1024 * 1024


def failure(code, message, status=409):
    raise DomainError("PACKAGE_RULE_CORRECTION_" + code, message, status, retryable=False)


def tag(revision, fingerprint):
    return etag("requirement-inventory", revision, fingerprint)


def request_body(scope, body):
    return {"scope": list(scope), **body}


def command_digest(scope, body, condition):
    return sha({"body": request_body(scope, body), "if_match": condition})


def require_schema(c):
    row = c.execute(
        "SELECT to_regclass('design.bid_package_rule_corrections') AS relation"
    ).fetchone()
    if row["relation"] is None:
        failure("UNAVAILABLE", "整包人工更正的数据库能力尚未安装", 503)


def raw_inventory(c, bid, inventory_id):
    row = c.execute(
        "SELECT manifest,digest FROM design.bid_package_requirement_inventories WHERE bid_id=%s AND id=%s",
        (bid, inventory_id),
    ).fetchone()
    if row is None:
        failure("NOT_FOUND", "所选要求清单不存在", 404)
    if digest(row["manifest"]) != row["digest"]:
        failure("CORRUPT", "要求清单原始摘要无法核验", 500)
    return row


def native_rules(c, bid, rule_set_id):
    return [
        row["value"]
        for row in c.execute(
            """SELECT to_jsonb(r)||jsonb_build_object('max_points',r.max_points::text) AS value
            FROM design.rule_items r WHERE r.bid_id=%s AND r.rule_set_id=%s ORDER BY r.kind,r.id""",
            (bid, rule_set_id),
        ).fetchall()
    ]


def authority(c, bid, inventory):
    manifest = inventory["manifest"]
    package = packages.load_revision(c, bid, manifest["authority_revision_id"])
    value = view(c, package)
    if (
        package.kind.value != "authority"
        or value["digest"] != manifest["authority_digest"]
        or value["identity"]["digest"] != manifest["identity_digest"]
    ):
        failure("CORRUPT", "要求清单与原权威包身份不一致", 500)
    return value


def evidence_rows(c, bid, authority_view, evidence_ids=None):
    """All selected evidence IDs bind the original member parse and declared physical parts."""
    revision = authority_view["manifest"]["revision_id"]
    rows = c.execute(
        """SELECT e.id::text AS evidence_id,m.member_id,
        m.document_version_id::text,m.parse_run_id::text,e.physical_page,
        e.text_content,e.digest AS evidence_digest
        FROM design.bid_package_members m
        JOIN design.evidence_blocks e ON e.bid_id=m.bid_id AND e.parse_id=m.parse_run_id
        WHERE m.bid_id=%s AND m.revision_id=%s
        AND (%s::uuid[] IS NULL OR e.id=ANY(%s::uuid[]))
        AND EXISTS(SELECT 1 FROM design.bid_package_parts p WHERE p.revision_id=m.revision_id
          AND p.member_id=m.member_id AND e.physical_page BETWEEN p.first_page AND p.last_page)
        ORDER BY m.ordinal,e.physical_page,e.ordinal,e.id""",
        (bid, revision, evidence_ids, evidence_ids),
    ).fetchall()
    return clean(rows)


def _record(c, bid, identity):
    row = c.execute(
        "SELECT * FROM design.bid_package_rule_corrections WHERE bid_id=%s AND id=%s",
        (bid, identity),
    ).fetchone()
    if row is None:
        failure("NOT_FOUND", "人工更正记录不存在", 404)
    if digest(row["manifest"]) != row["digest"]:
        failure("CORRUPT", "人工更正记录摘要无法核验", 500)
    return row


def _command(c, record):
    row = c.execute(
        "SELECT id,actor_id,command_kind,target_id,idempotency_key,request_digest,response FROM design.bid_package_rule_correction_command_receipts WHERE id=%s",
        (record["command_id"],),
    ).fetchone()
    m = record["manifest"]
    body = {"request": m["request"], "preview_digest": m["preview_digest"]}
    scope = tuple(
        m["scope"][key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
    )
    condition = tag(scope[2], m["base"]["inventory_digest"])
    expected = command_digest(scope, body, condition)
    if (
        row is None
        or str(row["actor_id"]) != m["actor_id"]
        or row["command_kind"] != KIND
        or str(row["target_id"]) != scope[3]
        or row["request_digest"] != expected
        or row["response"] is None
    ):
        failure("CORRUPT", "更正记录与原命令身份不一致", 500)
    command = {
        "command_id": str(row["id"]),
        "actor_id": str(row["actor_id"]),
        "idempotency_key": row["idempotency_key"],
        "request_digest": expected,
        "request": body,
        "if_match": condition,
    }
    inventory = raw_inventory(c, scope[0], m["result"]["inventory_id"])
    value = {
        "correction": {"manifest": m, "digest": record["digest"]},
        "inventory": inventory,
        "command": command,
    }
    if row["response"] != {
        "body": value,
        "status": 201,
        "headers": {"ETag": tag(scope[2], inventory["digest"])},
    }:
        failure("CORRUPT", "更正回执与原不可变结果不一致", 500)
    audits = c.execute(
        "SELECT actor_id::text,bid_id::text,payload FROM design.audit_entries WHERE command_id=%s AND event_type=%s LIMIT 2",
        (row["id"], EVENT),
    ).fetchall()
    expected_audit = {
        "correction_id": str(record["id"]),
        "digest": record["digest"],
        "inventory_id": inventory["manifest"]["id"],
    }
    if len(audits) != 1 or audits[0] != {
        "actor_id": m["actor_id"],
        "bid_id": scope[0],
        "payload": expected_audit,
    }:
        failure("CORRUPT", "更正回执与原人工审计不一致", 500)
    return value


def replay(c, actor, scope, key, body, condition):
    old = c.execute(
        """SELECT id,request_digest,response FROM design.commands WHERE actor_id=%s
        AND command_kind=%s AND target_id=%s AND idempotency_key=%s""",
        (actor, KIND, scope[3], key),
    ).fetchone()
    if old is None:
        return None
    if old["request_digest"] != command_digest(scope, body, condition):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同更正输入", 409)
    if old["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "更正操作尚未完成", 409)
    record = c.execute(
        "SELECT * FROM design.bid_package_rule_corrections WHERE command_id=%s",
        (old["id"],),
    ).fetchone()
    if record is None:
        failure("CORRUPT", "原命令没有对应的更正记录", 500)
    value = _command(c, record)
    if value["command"]["request"] != body or value["command"]["if_match"] != condition:
        failure("CORRUPT", "原回执未准确绑定本次恢复请求", 500)
    return deepcopy(old["response"])


def read_derivation(c, bid, inventory_manifest):
    """Bounded archive read; never recursively calls the inventory loader."""
    require_schema(c)
    head = inventory_manifest["human_derivation"]
    rows = c.execute(
        """WITH RECURSIVE chain AS (
          SELECT r.id,r.previous_id,r.sequence_no,1 AS depth
          FROM design.bid_package_rule_corrections r WHERE r.bid_id=%s AND r.id=%s
          UNION ALL
          SELECT r.id,r.previous_id,r.sequence_no,c.depth+1
          FROM design.bid_package_rule_corrections r JOIN chain c ON r.id=c.previous_id
          WHERE r.bid_id=%s AND c.depth<33
        ) SELECT id,previous_id,sequence_no,depth FROM chain ORDER BY sequence_no""",
        (bid, head["head_id"], bid),
    ).fetchall()
    if (
        len(rows) != head["length"]
        or not 1 <= len(rows) <= 32
        or rows[0]["previous_id"] is not None
    ):
        failure("CORRUPT", "人工派生链不完整或超过可验证范围", 500)
    ids = [row["id"] for row in rows]
    # Measure actual canonical JSON in PG before loading a potentially large chain.
    total = c.execute(
        """SELECT coalesce(sum(octet_length(convert_to(design.package_canonical_json(r.manifest),'UTF8'))
          +octet_length(convert_to(design.package_canonical_json(i.manifest),'UTF8'))
          +(SELECT coalesce(sum(octet_length(convert_to(design.package_canonical_json(
            to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text)),'UTF8'))),0)
            FROM design.rule_items q WHERE q.bid_id=r.bid_id AND q.rule_set_id=r.result_rule_set_id)),0) AS bytes
        FROM design.bid_package_rule_corrections r JOIN design.bid_package_requirement_inventories i ON i.id=r.base_inventory_id
        WHERE r.id=ANY(%s::uuid[])""",
        (ids,),
    ).fetchone()["bytes"]
    if total > MAX_CHAIN_BYTES:
        failure("TOO_LARGE", "人工派生链超过完整核验容量，请保留历史并重新准备明确输入", 413)
    root = raw_inventory(c, bid, inventory_manifest["extraction_basis"]["inventory_id"])
    steps = []
    for identity in ids:
        record = _record(c, bid, identity)
        _command(c, record)
        m = record["manifest"]
        result_rules = native_rules(c, bid, str(record["result_rule_set_id"]))
        rule_ids = [row["id"] for row in result_rules]
        decisions = [
            row["value"]
            for row in c.execute(
                "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE d.bid_id=%s AND d.id=ANY(%s::uuid[]) ORDER BY d.id",
                (bid, [item["decision_id"] for item in m["decision_bindings"]]),
            ).fetchall()
        ]
        carryovers = [
            row["value"]
            for row in c.execute(
                "SELECT to_jsonb(r) AS value FROM design.rule_carryovers r WHERE r.bid_id=%s AND r.new_rule_id=ANY(%s::uuid[]) ORDER BY r.new_rule_id",
                (bid, rule_ids),
            ).fetchall()
        ]
        steps.append(
            {
                "manifest": m,
                "digest": record["digest"],
                "base_inventory": raw_inventory(c, bid, str(record["base_inventory_id"])),
                "result_rules": result_rules,
                "decisions": decisions,
                "carryovers": carryovers,
            }
        )
    value = {"root_inventory": root, "steps": steps}
    if len(canonical(value)) > MAX_CHAIN_BYTES:
        failure("TOO_LARGE", "人工派生链超过完整核验容量", 413)
    return value


def inherited(c, bid, rule_set_id, authority_revision_id, authority_digest):
    if (
        c.execute(
            "SELECT to_regclass('design.bid_package_rule_corrections') AS relation"
        ).fetchone()["relation"]
        is None
    ):
        return None
    row = c.execute(
        "SELECT manifest,digest FROM design.bid_package_rule_corrections WHERE bid_id=%s AND result_rule_set_id=%s",
        (bid, rule_set_id),
    ).fetchone()
    if row is None:
        return None
    m = row["manifest"]
    if (
        m["authority"]["revision_id"] != authority_revision_id
        or m["authority"]["digest"] != authority_digest
    ):
        failure("AUTHORITY_CHANGED", "人工更正来源不属于所选权威包，需要重新抽取并核对", 409)
    return {
        "extraction_binding": "frozen_extraction_plus_human_derivation",
        "extraction_basis": m["extraction_basis"],
        "human_derivation": {
            "version": "package-rule-derivation/1",
            "head_id": m["id"],
            "head_digest": row["digest"],
            "length": m["sequence_no"],
        },
    }


def insert(c, value):
    m = value["manifest"]
    s = m["scope"]
    c.execute(
        """INSERT INTO design.bid_package_rule_corrections
        (id,bid_id,package_id,revision_id,base_inventory_id,result_inventory_id,root_inventory_id,
        base_rule_set_id,result_rule_set_id,previous_id,sequence_no,actor_id,command_id,manifest,digest,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            m["id"],
            s["bid_id"],
            s["package_id"],
            s["revision_id"],
            s["inventory_id"],
            m["result"]["inventory_id"],
            m["extraction_basis"]["inventory_id"],
            m["base"]["rule_set_id"],
            m["result"]["rule_set_id"],
            m["previous"]["id"] if m["previous"] else None,
            m["sequence_no"],
            m["actor_id"],
            m["command_id"],
            Jsonb(m),
            value["digest"],
            m["created_at"],
        ),
    )


def _scope_inventory(c, scope):
    from packages.domain.bid_package_requirement_repository import load_inventory

    return load_inventory(c, *scope)


def load(c, scope, correction_id):
    inventory = _scope_inventory(c, scope)
    record = _record(c, scope[0], correction_id)
    m = record["manifest"]
    if tuple(m["scope"][key] for key in ("bid_id", "package_id", "revision_id")) != tuple(
        scope[:3]
    ):
        failure("NOT_FOUND", "人工更正记录不属于所选包修订", 404)
    from packages.domain.package_rule_corrections import extraction_basis

    if m["extraction_basis"] != extraction_basis(inventory):
        failure("NOT_FOUND", "人工更正记录不属于所选清单的原抽取链", 404)
    value = _command(c, record)
    # Verify the exact resulting inventory; never replace it with the current head.
    actual = _scope_inventory(c, (*scope[:3], m["result"]["inventory_id"]))
    if value["inventory"] != actual:
        failure("CORRUPT", "人工更正结果与原清单不一致", 500)
    return value


def history(c, scope, cursor=None, limit=20):
    from packages.domain.package_rule_corrections import extraction_basis

    inventory = _scope_inventory(c, scope)
    root = extraction_basis(inventory)
    if type(limit) is not int or not 1 <= limit <= 50:
        failure("INVALID", "历史页数量必须为1至50", 422)
    identity = sha(
        {"kind": "package-rule-correction-history/1", "scope": list(scope), "root": root}
    )
    after = pagination.decode(cursor, identity)
    rows = c.execute(
        """SELECT id::text,digest,created_at,actor_id::text,base_inventory_id::text,result_inventory_id::text,
        jsonb_array_length(manifest->'additions') AS added,
        (SELECT count(*) FROM jsonb_array_elements(manifest->'mappings') x WHERE x->>'op'='replace') AS replaced,
        (SELECT count(*) FROM jsonb_array_elements(manifest->'mappings') x WHERE x->>'op'='withdraw') AS withdrawn
        FROM design.bid_package_rule_corrections
        WHERE bid_id=%s AND package_id=%s AND revision_id=%s AND root_inventory_id=%s
        AND (%s::uuid IS NULL OR (created_at,id)<(%s::timestamptz,%s::uuid))
        ORDER BY created_at DESC,id DESC LIMIT %s""",
        (
            *scope[:3],
            root["inventory_id"],
            after[-1] if after else None,
            after[0] if after else None,
            after[-1] if after else None,
            limit + 1,
        ),
    ).fetchall()
    items = clean(rows[:limit])
    return {
        "scope": dict(
            zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
        ),
        "items": items,
        "has_more": len(rows) > limit,
        "next_cursor": pagination.encode(identity, [items[-1]["created_at"], items[-1]["id"]])
        if len(rows) > limit
        else None,
    }


def _evidence_item(row, members, *, full=False):
    member = members[row["member_id"]]
    value = clean(row)
    value.pop("member_ordinal", None)
    text = value.pop("text_content")
    value["file_digest"] = member["file_digest"]
    value["part_ids"] = [
        part["part_id"]
        for part in member["parts"]
        if part["first_page"] <= value["physical_page"] <= part["last_page"]
    ]
    value["text_content" if full else "excerpt"] = text if full else text[:360]
    return value


def evidence(c, scope, *, evidence_id=None, cursor=None, limit=20):
    inventory = _scope_inventory(c, scope)
    official = authority(c, scope[0], inventory)
    members = {item["member_id"]: item for item in official["manifest"]["members"]}
    identity = sha(
        {
            "kind": "package-rule-correction-evidence/1",
            "scope": list(scope),
            "inventory_digest": inventory["digest"],
        }
    )
    after = pagination.decode(cursor, identity)
    sort = json.loads(after[0]) if after else [0, 0, 0]
    if (
        not isinstance(sort, list)
        or len(sort) != 3
        or any(type(v) is not int or v < 0 for v in sort)
    ):
        failure("INVALID", "原页证据游标不合法", 422)
    if type(limit) is not int or not 1 <= limit <= 50:
        failure("INVALID", "证据页数量必须为1至50", 422)
    rows = c.execute(
        """SELECT e.id::text AS evidence_id,m.member_id,m.ordinal AS member_ordinal,
        m.document_version_id::text,m.parse_run_id::text,e.physical_page,e.ordinal,e.kind,
        e.digest AS evidence_digest,e.text_content
        FROM design.bid_package_members m JOIN design.evidence_blocks e ON e.bid_id=m.bid_id AND e.parse_id=m.parse_run_id
        WHERE m.bid_id=%s AND m.revision_id=%s AND (%s::uuid IS NULL OR e.id=%s::uuid)
        AND (%s::uuid IS NULL OR (m.ordinal,e.physical_page,e.ordinal,e.id)>(%s,%s,%s,%s::uuid))
        AND EXISTS(SELECT 1 FROM design.bid_package_parts p WHERE p.revision_id=m.revision_id AND p.member_id=m.member_id
        AND e.physical_page BETWEEN p.first_page AND p.last_page)
        ORDER BY m.ordinal,e.physical_page,e.ordinal,e.id LIMIT %s""",
        (
            scope[0],
            official["manifest"]["revision_id"],
            evidence_id,
            evidence_id,
            after[-1] if after else None,
            *sort,
            after[-1] if after else None,
            1 if evidence_id else limit + 1,
        ),
    ).fetchall()
    base = {
        "scope": dict(
            zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
        ),
        "inventory_digest": inventory["digest"],
        "authority": {
            "revision_id": official["manifest"]["revision_id"],
            "digest": official["digest"],
            "identity_digest": official["identity"]["digest"],
        },
    }
    if evidence_id:
        if not rows:
            failure("EVIDENCE_NOT_FOUND", "原页证据不属于所选权威包的确切解析与页段", 404)
        return base | {"evidence": _evidence_item(rows[0], members, full=True)}
    last = rows[limit - 1] if len(rows) > limit else None
    return base | {
        "items": [_evidence_item(row, members) for row in rows[:limit]],
        "has_more": len(rows) > limit,
        "next_cursor": pagination.encode(
            identity,
            [
                json.dumps([last["member_ordinal"], last["physical_page"], last["ordinal"]]),
                last["evidence_id"],
            ],
        )
        if last
        else None,
    }
