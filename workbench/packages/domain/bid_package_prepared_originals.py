"""Bind fresh original verification and publication checks to one prepared record.

No task, outbox, transaction commit or public dispatch permit belongs to this port.
"""

import json
from dataclasses import dataclass, field

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain import bid_package_frozen_originals as originals
from packages.domain.bid_package_service import lock_bid
from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.runtime import DomainError, connection
from packages.knowledge.sources import lock_graph


@dataclass(frozen=True)
class VerifiedPreparedOriginals:
    input_id: str
    digest: str
    _prepared: PreparedExecutionInput = field(repr=False)
    _originals: originals.VerifiedFrozenOriginals = field(repr=False)


def _load(c, scope, frozen_id, input_id, prepared_digest):
    packet = inputs.load_packet(c, scope, frozen_id, input_id)
    if packet.digest != prepared_digest:
        raise DomainError(
            "PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不一致，请重读原记录", 409
        )
    return packet


def _assert_snapshot(packet: PreparedExecutionInput, snapshot):
    prepared = packet.snapshot()
    prepared.pop("version")
    originals.assert_same(prepared, snapshot)


def verify(scope, frozen_id, input_id, prepared_digest):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = _load(c, scope, frozen_id, input_id, prepared_digest)
    manifest = packet.view()["manifest"]
    binding = manifest["identity"]["binding"]
    verified = originals.verify(
        scope, frozen_id, binding["frozen_digest"], binding["context_digest"]
    )
    _assert_snapshot(packet, json.loads(verified._snapshot_text))
    if verified.execution_identity(manifest["identity"]["rerun"]) != manifest["identity"]:
        raise DomainError("PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入执行身份不符", 409)
    return VerifiedPreparedOriginals(input_id, prepared_digest, packet, verified)


def recheck_for_publication(c, verified: VerifiedPreparedOriginals):
    if c.autocommit:
        raise ValueError("Publication requires a transaction")
    packet = verified._prepared
    lock_bid(c, packet.scope[0])
    lock_graph(c)
    stored = _load(c, packet.scope, packet.frozen_id, verified.input_id, verified.digest)
    if stored.view() != packet.view() or stored.snapshot() != packet.snapshot():
        raise DomainError("PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入记录已变化", 409)
    current = originals.capture(
        c, packet.scope, packet.frozen_id, verified._originals.frozen_digest
    )
    originals.assert_same(json.loads(verified._originals._snapshot_text), current)
    _assert_snapshot(stored, current)
    return originals.assert_publication_ready(current["result"], verified._originals.context_digest)
