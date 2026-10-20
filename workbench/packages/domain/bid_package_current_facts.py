"""Bounded current fact reads for explicit frozen workspaces, never use qualification."""

import json
from copy import deepcopy

from packages.contracts.bid_package_requirements_api import valid
from packages.domain import bid_package_review_input_repository as inputs
from packages.domain.bid_package_prepared_facts import preview
from packages.domain.package_review_context import read_facts
from packages.domain.review_identity import utc
from packages.domain.runtime import DomainError, connection, sha
from packages.identity import pagination

FLAGS = dict(
    original_bytes_verified=False,
    facts_qualified=False,
    review_ready=False,
    launch_available=False,
    publication_authorized=False,
    required_facts_assessment="not_performed",
)


def _load(c, scope, frozen_id, frozen_digest):
    packet = inputs.load_input(c, scope, frozen_id)
    if packet.digest != frozen_digest:
        raise DomainError(
            "PACKAGE_REVIEW_FROZEN_INPUT_CHANGED", "冻结记录摘要与明确选择不一致", 409
        )
    head = c.execute(
        "SELECT fact_set_id::text AS id,revision FROM design.fact_heads WHERE bid_id=%s",
        (scope[0],),
    ).fetchone() or dict(id=None, revision=0)
    return packet, head, packet.evidence()


def _binding(scope, frozen_id, packet):
    return dict(
        zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
    ) | dict(frozen_input_id=frozen_id, frozen_digest=packet.digest)


def _items(c, scope, root, ids, at):
    if not ids:
        return {}
    parses = {(doc["document_version_id"], doc["parse_id"]) for doc in root["documents"]}
    rows = read_facts(c, scope[0], parses, fact_ids=ids, as_of=at)["items"]
    result = {row["fact"]["id"]: row for row in rows}
    if set(result) != set(ids) or len(result) != len(rows):
        raise DomainError("PACKAGE_CURRENT_FACTS_CORRUPT", "当前事实与明确事实集不一致", 500)
    return result


def _summary(item):
    decision = item["decision"]
    recorded = (
        decision["decision"]
        if decision
        and decision["object_kind"] == "fact"
        and decision["decision"] in ("confirmed", "rejected")
        else "pending"
    )
    return preview(item) | dict(
        confirmation_recorded=recorded,
        decision_id=decision["id"] if decision else None,
        frozen_evidence_status="selected_parse"
        if item["scope_binding"] == "selected_frozen_parse"
        else "unproven",
    )


def _checked(name, value):
    if not valid(name, value):
        raise DomainError("PACKAGE_CURRENT_FACTS_CORRUPT", "当前事实读取结果不符合协议", 500)
    return deepcopy(value)


def _editable_fact(item):
    fact = item["fact"]
    raw = fact["value_jsonb_text"].strip()
    if raw.startswith('"') or raw in ("true", "false", "null"):
        candidate = {
            key: fact[key] for key in ("subject", "scope", "name", "unit", "evidence_ids")
        } | dict(value=json.loads(raw))
        if valid("PackageEditableFact", candidate) and all(
            candidate[key].strip() for key in ("subject", "scope", "name")
        ):
            return candidate
    return None


def directory(scope, frozen_id, frozen_digest, limit=20, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainError("INVALID_REQUEST", "每页事实数量须为1至100", 422)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet, head, root = _load(c, scope, frozen_id, frozen_digest)
        collection = sha(
            dict(
                directory="current-package-facts/1",
                scope=scope,
                frozen_id=frozen_id,
                frozen_digest=packet.digest,
                head=head,
            )
        )
        after = pagination.decode(cursor, collection)
        if after and (
            after[0] != sha(head)
            or c.execute(
                "SELECT 1 FROM design.fact_items WHERE bid_id=%s AND fact_set_id=%s AND id=%s",
                (scope[0], head["id"], str(after[-1])),
            ).fetchone()
            is None
        ):
            raise DomainError("INVALID_CURSOR", "事实列表已变化，请重新读取", 422)
        ids = [
            row["id"]
            for row in c.execute(
                "SELECT id::text FROM design.fact_items WHERE bid_id=%s AND fact_set_id=%s AND (%s::uuid IS NULL OR id>%s::uuid) ORDER BY id LIMIT %s",
                (
                    scope[0],
                    head["id"],
                    str(after[-1]) if after else None,
                    str(after[-1]) if after else None,
                    limit + 1,
                ),
            ).fetchall()
        ]
        count = c.execute(
            "SELECT count(*) AS n FROM design.fact_items WHERE bid_id=%s AND fact_set_id=%s",
            (scope[0], head["id"]),
        ).fetchone()["n"]
        at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
        current = _items(c, scope, root, ids[:limit], at)
        items = [_summary(current[value]) for value in ids[:limit]]
        more = len(ids) > limit
        return _checked(
            "PackageCurrentFactPage",
            dict(
                version="package-current-facts/1",
                kind="current_package_facts",
                binding=_binding(scope, frozen_id, packet),
                head=head,
                checked_at=at,
                fact_count=count,
                source_packages=[
                    dict(
                        role=role,
                        package_id=root["selection"][role]["manifest"]["package_id"],
                        revision_id=root["selection"][role]["manifest"]["revision_id"],
                        digest=root["selection"][role]["digest"],
                    )
                    for role in ("target", "authority")
                ],
                items=items,
                has_more=more,
                next_cursor=pagination.encode(collection, [sha(head), items[-1]["fact_id"]])
                if more
                else None,
                **FLAGS,
            ),
        )


def detail(scope, frozen_id, frozen_digest, fact_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet, head, root = _load(c, scope, frozen_id, frozen_digest)
        if (
            c.execute(
                "SELECT 1 FROM design.fact_items WHERE bid_id=%s AND fact_set_id=%s AND id=%s",
                (scope[0], head["id"], fact_id),
            ).fetchone()
            is None
        ):
            raise DomainError(
                "PACKAGE_CURRENT_FACT_NOT_FOUND", "该事实已不在当前事实集中，请重读列表", 404
            )
        at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
        item = _items(c, scope, root, [fact_id], at)[fact_id]
        editable = _editable_fact(item)
        parses = {(doc["document_version_id"], doc["parse_id"]) for doc in root["documents"]}
        references = [
            row | {"frozen_parse_member": (row["document_version_id"], row["parse_id"]) in parses}
            for row in item["evidence"][:100]
        ]
        return _checked(
            "PackageCurrentFactDetail",
            dict(
                version="package-current-fact/1",
                kind="current_package_fact",
                binding=_binding(scope, frozen_id, packet),
                head=head,
                checked_at=at,
                summary=_summary(item),
                editability="editable" if editable is not None else "unsupported_or_oversized",
                editable_fact=editable,
                evidence_references=references,
                evidence_truncated=len(item["evidence"]) > 100,
                **FLAGS,
            ),
        )
