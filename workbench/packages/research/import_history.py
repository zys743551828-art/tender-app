"""Discoverable import batches and recoverable acknowledgements before object IO."""

import json
from uuid import UUID

from packages.domain.runtime import DomainError, clean, fetch, sha
from packages.research import batches, importing

PREVIEW_TARGET = UUID("59696bb3-834e-4768-80fb-5662402f6975")
PREVIEW_KIND = "preview-historical-import"
CONFIRM_KIND = "confirm-historical-import"


def checked_key(key):
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(c) < 32 for c in key):
        raise DomainError("IDEMPOTENCY_REQUIRED", "请保留有效的历史导入操作幂等键", 428)


def replay(c, actor, kind, target, key, body, condition=None):
    """A committed result must remain recoverable if its private object is unavailable."""
    checked_key(key)
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s "
        "AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, kind, target, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": body, "if_match": condition}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一导入请求的资料或条件已变化", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "原导入请求尚未形成回执，请保留原请求", 409)
    return row["response"]


def receipt(command, actor, kind, target, key, body, condition=None):
    return clean(
        {
            "command_id": command.id,
            "actor_id": actor,
            "command_kind": kind,
            "target_id": target,
            "idempotency_key": key,
            "request_digest": sha({"body": body, "if_match": condition}),
            "if_match": condition,
        }
    )


def manifest(records):
    value = {"schema": "historical-import/1", "records": records}
    raw = json.dumps(
        clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(raw) > batches.MAX_MANIFEST_BYTES:
        raise DomainError(
            "IMPORT_MANIFEST_TOO_LARGE", "导入清单超过 8 MiB，请明确拆分批次后重新预检查", 422
        )
    return value


def directory(c, *, mode=None, limit=20, offset=0):
    if mode not in (None, "dry_run", "confirmed_import"):
        raise DomainError("INVALID_REQUEST", "请选择有效的导入批次状态", 422)
    if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
        raise DomainError("INVALID_REQUEST", "导入目录分页超出范围", 422)
    # The original batch table has no timestamp. The immutable creation audit
    # supplies the actual time; an absent audit stays unknown instead of using now().
    rows = c.execute(
        "SELECT b.id,b.mode,b.revision,b.created_by,a.created_at,"
        "n.total,n.pending,n.imported,n.errors FROM design.import_batches b "
        "LEFT JOIN LATERAL (SELECT created_at FROM design.audit_entries "
        "WHERE event_type='historical_import.preview_created' "
        "AND payload->>'batch_id'=b.id::text ORDER BY created_at,id LIMIT 1) a ON true "
        "CROSS JOIN LATERAL (SELECT count(*) AS total,"
        "count(*) FILTER(WHERE state='pending') AS pending,"
        "count(*) FILTER(WHERE state='imported') AS imported,"
        "count(*) FILTER(WHERE state IN ('conflict','failed')) AS errors "
        "FROM design.import_records WHERE batch_id=b.id) n "
        "WHERE (%s::text IS NULL OR b.mode=%s) "
        "ORDER BY a.created_at DESC NULLS LAST,b.id DESC LIMIT %s OFFSET %s",
        (mode, mode, limit + 1, offset),
    ).fetchall()
    return clean(
        {
            "items": [
                {key: row[key] for key in ("id", "mode", "revision", "created_by", "created_at")}
                | {"counts": {key: row[key] for key in ("total", "pending", "imported", "errors")}}
                for row in rows[:limit]
            ],
            "next_offset": offset + limit if len(rows) > limit else None,
        }
    )


def source_metadata(c, identity):
    batch = fetch(c, "SELECT manifest_blob_id FROM design.import_batches WHERE id=%s", (identity,))
    return batches.manifest_metadata(c, batch["manifest_blob_id"], importing.IMPORT_MEDIA)


def source(identity, metadata):
    """Call after closing the metadata transaction; return only the exact saved request."""
    from pydantic import ValidationError

    from packages.research.import_contracts import HistoricalImportRequest

    manifest = batches.read_manifest(metadata)
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "records"}:
        raise DomainError("IMPORT_MANIFEST_INVALID", "原批次清单形状不符合导入协议", 409)
    if manifest["schema"] != "historical-import/1":
        raise DomainError("IMPORT_MANIFEST_INVALID", "原批次清单用途不匹配", 409)
    try:
        HistoricalImportRequest.model_validate({"records": manifest["records"]})
    except ValidationError:
        raise DomainError("IMPORT_MANIFEST_INVALID", "原批次记录不符合导入协议", 409) from None
    return clean(
        {
            "batch_id": identity,
            "manifest_blob_id": metadata["id"],
            "manifest_digest": metadata["digest"],
            "request": {"records": manifest["records"]},
            "source_matches_saved_manifest": True,
        }
    )
