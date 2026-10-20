"""Verify exact frozen originals outside transactions, then recheck under publication locks.

The private receipt is an internal observation, never a serialized dispatch permit.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from packages.domain import original_verification
from packages.domain.bid_package_review_documents import read_member
from packages.domain.bid_package_review_eligibility import read_in_snapshot
from packages.domain.bid_package_service import lock_bid
from packages.domain.package_review_execution_identity import identify
from packages.domain.runtime import DomainError, clean, connection
from packages.knowledge.sources import lock_graph


@dataclass(frozen=True)
class VerifiedFrozenOriginals:
    scope: tuple[str, str, str, str]
    input_id: str
    frozen_digest: str
    context_digest: str
    _snapshot_text: str = field(repr=False)

    def execution_identity(self, rerun: dict[str, Any] | None = None) -> dict[str, Any]:
        return identify(json.loads(self._snapshot_text)["binding"], rerun)

    def observation(self) -> dict[str, Any]:
        # Each consumer receives a copy; locators and private evidence never leave this port.
        snapshot = json.loads(self._snapshot_text)
        return snapshot["result"] | {
            "kind": "frozen_originals_observation",
            "original_verification": "verified_at_observation",
            "originals": [
                {
                    "role": doc["package_role"],
                    "member_id": doc["member_id"],
                    "document_version_id": doc["document_version_id"],
                    "parse_run_id": doc["parse_id"],
                    "file_digest": doc["digest"],
                    "byte_size": doc["byte_size"],
                }
                for doc in snapshot["documents"]
            ],
        }


def capture(c, scope: tuple[str, str, str, str], input_id: str, frozen_digest: str):
    packet, root, observations, result = read_in_snapshot(c, scope, input_id, frozen_digest)
    if result["parse_evidence_status"] != "matched":
        raise DomainError("PACKAGE_REVIEW_EVIDENCE_CHANGED", "精确解析证据已变化，未核验原件", 409)
    documents = [
        read_member(c, scope[0], member) | {"package_role": role}
        for role in ("target", "authority")
        for member in root["selection"][role]["manifest"]["members"]
    ]
    manifest = packet.view()["manifest"]
    context = result["current_context"]
    return {
        "binding": {
            **dict(
                zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
            ),
            "identity_digest": root["selection"]["target"]["identity"]["digest"],
            "frozen_input_id": input_id,
            "frozen_digest": frozen_digest,
            "input_digest": manifest["input_digest"],
            "evidence_digest": manifest["evidence_digest"],
            "context_digest": context["semantic_digest"],
            "method_digest": context["method_digest"],
            "policy_digest": context["policy_digest"],
            "purpose": context["purpose"],
        },
        "result": result,
        "observations": clean({k: v for k, v in observations.items() if k != "at"}),
        "documents": clean(documents),
    }


def stable(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = snapshot["result"]
    return snapshot | {
        "result": {k: v for k, v in result.items() if k not in {"checked_at", "current_context"}}
        | {
            "current_context": {
                k: v
                for k, v in result["current_context"].items()
                if k not in {"as_of", "snapshot_digest"}
            }
        }
    }


def assert_same(before: dict[str, Any], after: dict[str, Any]):
    if stable(before) != stable(after):
        raise DomainError(
            "PACKAGE_REVIEW_INPUT_CHANGED", "原件核验后输入或当前条件已变化，未授予发布许可", 409
        )


def read(scope: tuple[str, str, str, str], input_id: str, frozen_digest: str):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return capture(c, scope, input_id, frozen_digest)


def verify(
    scope: tuple[str, str, str, str], input_id: str, frozen_digest: str, context_digest: str
) -> VerifiedFrozenOriginals:
    before = read(scope, input_id, frozen_digest)
    if before["result"]["current_context"]["semantic_digest"] != context_digest:
        raise DomainError("PACKAGE_REVIEW_CONTEXT_CHANGED", "当前上下文与明确选择不一致", 409)
    # Both snapshots are closed before provider calls. Every logical member remains in order.
    for document in before["documents"]:
        original_verification.verify(document)
    after = read(scope, input_id, frozen_digest)
    assert_same(before, after)
    text = json.dumps(
        after, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return VerifiedFrozenOriginals(scope, input_id, frozen_digest, context_digest, text)


def recheck_for_publication(c, verified: VerifiedFrozenOriginals):
    # The caller owns the eventual write transaction; no provider IO belongs here.
    # lock_graph also enforces a fresh READ COMMITTED transaction, never a stale RR snapshot.
    if c.autocommit:
        raise ValueError("Publication requires a transaction")
    lock_bid(c, verified.scope[0])
    lock_graph(c)
    current = capture(c, verified.scope, verified.input_id, verified.frozen_digest)
    assert_same(json.loads(verified._snapshot_text), current)
    result = current["result"]
    if (
        result["current_context"]["semantic_digest"] != verified.context_digest
        or result["blockers"]
        or result["review_ready"] is not True
        or result["launch_available"] is not True
        or result["publication_authorized"] is not True
    ):
        raise DomainError(
            "PACKAGE_REVIEW_EXECUTION_BLOCKED", "整包执行条件尚未满足，未创建任务或发布结果", 409
        )
    return result
