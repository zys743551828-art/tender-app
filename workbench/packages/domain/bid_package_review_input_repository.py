"""Immutable whole-package input persistence and replay; never reads current heads."""

from typing import Any

from psycopg.types.json import Jsonb

from packages.domain.bid_packages import PackageError
from packages.domain.package_review_frozen_input import consume
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha

KIND = "package-review-input-freeze"


def replay(c: Any, actor: str, scope: tuple[str, str, str, str], key: str, body: dict[str, Any]):
    old = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, KIND, scope[3], key),
    ).fetchone()
    if old is None:
        return None
    if old["request_digest"] != sha({"body": body, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同输入", 409)
    stored = old["response"]
    if stored is None:
        raise DomainError("COMMAND_INCOMPLETE", "操作尚未完成", 409)
    manifest = stored["body"]["manifest"]
    if tuple(manifest[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")) != scope:
        raise PackageError("PACKAGE_REVIEW_FROZEN_INPUT_NOT_FOUND")
    return stored


def insert(c: Any, manifest: dict[str, Any], evidence_text: str):
    identity = digest(manifest)
    c.execute(
        """INSERT INTO design.bid_package_review_inputs
    (id,bid_id,package_id,revision_id,inventory_id,actor_id,command_id,manifest,digest,evidence_text,evidence_digest,frozen_at)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        tuple(
            manifest[k]
            for k in (
                "id",
                "bid_id",
                "package_id",
                "revision_id",
                "inventory_id",
                "actor_id",
                "command_id",
            )
        )
        + (
            Jsonb(manifest),
            identity,
            evidence_text,
            manifest["evidence_digest"],
            manifest["frozen_at"],
        ),
    )
    return {"manifest": manifest, "digest": identity}


def load_input(c: Any, scope: tuple[str, str, str, str], input_id: str):
    row = c.execute(
        """SELECT manifest,digest,evidence_text,evidence_digest FROM design.bid_package_review_inputs
    WHERE bid_id=%s AND package_id=%s AND revision_id=%s AND inventory_id=%s AND id=%s""",
        (*scope, input_id),
    ).fetchone()
    if row is None:
        raise PackageError("PACKAGE_REVIEW_FROZEN_INPUT_NOT_FOUND")
    return consume(row, scope, input_id)


def load(c: Any, scope: tuple[str, str, str, str], input_id: str):
    return load_input(c, scope, input_id).view()
