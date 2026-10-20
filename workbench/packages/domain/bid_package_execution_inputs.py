"""Prepare immutable execution inputs under locks; never tasks or outbox messages."""

import json

from psycopg.types.json import Jsonb

from packages.domain import bid_package_execution_input_repository as repository
from packages.domain.bid_package_frozen_originals import assert_same, capture, verify
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import Command, DomainError, connection, fetch, sha, uid
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable


def save(actor, scope, frozen_id, key, body):
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(c, actor, scope, frozen_id, key, body)
    if old:
        return old, True
    verified = verify(scope, frozen_id, body["frozen_digest"], body["context_digest"])
    identity = verified.execution_identity(body["rerun"])
    snapshot = json.loads(verified._snapshot_text)
    snapshot["version"] = "package-review-prepared-snapshot/1"
    text = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    with connection() as c:
        lock_bid(c, scope[0])
        cmd = Command(c, actor, repository.KIND, frozen_id, key, body)
        if cmd.replay:
            return cmd.replay, True
        assert_work_writable(c, scope[0])
        lock_graph(c)
        assert_same(
            json.loads(verified._snapshot_text), capture(c, scope, frozen_id, body["frozen_digest"])
        )
        m = {
            "version": "package-review-execution-input/1",
            "kind": "prepared_input",
            "id": str(uid()),
            **dict(
                zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
            ),
            "frozen_input_id": frozen_id,
            "actor_id": actor,
            "command_id": str(cmd.id),
            "identity": identity,
            "execution_context": snapshot["result"]["current_context"],
            "snapshot_digest": sha(text.encode()),
            "originals_verified_at": snapshot["result"]["checked_at"],
            "saved_at": utc(fetch(c, "SELECT clock_timestamp() AS at")["at"].isoformat()),
            "blockers": snapshot["result"]["blockers"],
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        }
        value = {"manifest": m, "digest": digest(m)}
        c.execute(
            "INSERT INTO design.bid_package_execution_inputs(id,bid_id,frozen_input_id,actor_id,command_id,manifest,digest,snapshot_text,snapshot_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                m["id"],
                scope[0],
                frozen_id,
                actor,
                cmd.id,
                Jsonb(m),
                value["digest"],
                text,
                m["snapshot_digest"],
            ),
        )
        stored = cmd.finish(value, 201)
    return stored, False
