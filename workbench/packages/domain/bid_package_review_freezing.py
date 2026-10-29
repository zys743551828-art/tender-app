"""Freeze verified inputs idempotently; provider IO never holds the write transaction."""

import json
from typing import Any

from packages.domain import bid_package_review_input_repository as repository
from packages.domain import original_verification
from packages.domain.bid_package_original_verification import read_in_snapshot, read_input
from packages.domain.bid_package_service import lock_bid
from packages.domain.package_review_identity import summary
from packages.domain.review_data import frozen_documents
from packages.domain.review_identity import utc
from packages.domain.runtime import Command, DomainError, clean, connection, fetch, sha, uid
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable


def freeze(actor: str, scope: tuple[str, str, str, str], key: str | None, body: dict[str, Any]):
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(c, actor, scope, key, body)
    if old:
        return old, True
    before = read_input(*scope, body)
    if before.execution_context["semantic_digest"] != body["context_digest"]:
        raise DomainError("PACKAGE_REVIEW_CONTEXT_CHANGED", "候选上下文已变化，请重新核对", 409)
    for document in before.documents:
        original_verification.verify(document)
    with connection() as c:
        lock_bid(c, scope[0])
        cmd = Command(c, actor, repository.KIND, scope[3], key, body)
        if cmd.replay:
            return cmd.replay, True
        assert_work_writable(c, scope[0])
        lock_graph(c)
        current = read_in_snapshot(c, *scope, body)
        if (
            before.manifest != current.manifest
            or before.documents != current.documents
            or before.stable_observations() != current.stable_observations()
            or before.blockers != current.blockers
            or current.execution_context["semantic_digest"] != body["context_digest"]
        ):
            raise DomainError(
                "PACKAGE_REVIEW_INPUT_CHANGED", "核验期间输入或来源状态已变化，未保存冻结输入", 409
            )
        root = {
            "version": "package-review-evidence/1",
            "selection": current.manifest,
            "context": current.execution_context["manifest"],
            "documents": frozen_documents(current.documents),
        }
        evidence_text = json.dumps(
            clean(root), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        manifest = {
            "version": "package-review-frozen-input/1",
            "kind": "frozen_input",
            "id": str(uid()),
            **dict(
                zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
            ),
            "actor_id": actor,
            "command_id": str(cmd.id),
            "input_digest": current.digest,
            "context_digest": body["context_digest"],
            "evidence_digest": sha(evidence_text.encode("utf-8")),
            "execution_context": summary(current.execution_context),
            "as_of": current.execution_context["manifest"]["as_of"],
            "frozen_at": utc(fetch(c, "SELECT clock_timestamp() AS at")["at"].isoformat()),
            "blockers": current.blockers,
            "review_ready": False,
            "launch_available": False,
        }
        value = repository.insert(c, manifest, evidence_text)
        stored = cmd.finish(value, 201)
    # Deferred commit checks must finish before returning a successful ACK.
    return stored, False
