"""Explicit synthetic ports test orchestration, not PostgreSQL or original byte quality."""

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from packages.domain import bid_package_prepared_originals as prepared
from packages.domain.bid_package_frozen_originals import VerifiedFrozenOriginals
from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.package_review_execution_identity import identify
from packages.domain.runtime import DomainError


@pytest.fixture
def ports(monkeypatch):
    vector = json.loads(
        (Path(__file__).parent / "fixtures/package-review-execution-vectors.json").read_text(
            "utf-8"
        )
    )[0]
    identity = vector["expected"]
    binding = identity["binding"]
    scope = tuple(binding[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id"))
    snapshot = {
        "binding": binding,
        "context": {
            "manifest": {"as_of": "old", "facts": {"value": "private-fact"}},
            "semantic_digest": "context",
            "snapshot_digest": "old",
        },
        "observations": {"head": "original-head"},
        "documents": [{"parse_id": "exact-parse", "object_key": "private-locator"}],
        "result": {
            "checked_at": "old",
            "current_context": {
                "as_of": "old",
                "snapshot_digest": "old",
                "semantic_digest": binding["context_digest"],
            },
            "blockers": ["PACKAGE_REVIEW_EXECUTOR_NOT_READY"],
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        },
    }
    packet = PreparedExecutionInput(
        scope,
        binding["frozen_input_id"],
        "prepared-id",
        "prepared-sha",
        json.dumps({"manifest": {"identity": identity}}),
        json.dumps(snapshot | {"version": "package-review-prepared-snapshot/1"}),
    )
    state = {
        "active": 0,
        "events": [],
        "packet": packet,
        "snapshot": snapshot,
        "scope": scope,
        "binding": binding,
        "during_verify": None,
    }

    class Connection:
        autocommit = False

        def execute(self, statement):
            state["events"].append(statement)

    @contextmanager
    def connection():
        state["active"] += 1
        try:
            yield Connection()
        finally:
            state["active"] -= 1

    def load(c, given_scope, frozen_id, input_id):
        assert (
            given_scope == scope
            and frozen_id == binding["frozen_input_id"]
            and input_id == "prepared-id"
        )
        state["events"].append("load")
        return state["packet"]

    def verify(given_scope, frozen_id, digest, context):
        assert (
            state["active"] == 0
            and given_scope == scope
            and frozen_id == binding["frozen_input_id"]
        )
        assert digest == binding["frozen_digest"] and context == binding["context_digest"]
        state["events"].append("original-io")
        if state["during_verify"]:
            state["during_verify"]()
        return VerifiedFrozenOriginals(
            scope, frozen_id, digest, context, json.dumps(state["snapshot"])
        )

    monkeypatch.setattr(prepared, "connection", connection)
    monkeypatch.setattr(prepared.inputs, "load_packet", load)
    monkeypatch.setattr(prepared.originals, "verify", verify)
    monkeypatch.setattr(prepared.originals, "capture", lambda *args: deepcopy(state["snapshot"]))
    monkeypatch.setattr(prepared, "lock_bid", lambda *args: state["events"].append("bid-lock"))
    monkeypatch.setattr(prepared, "lock_graph", lambda *args: state["events"].append("graph-lock"))
    state["connection"] = Connection
    return state


def verify(state, digest="prepared-sha"):
    return prepared.verify(
        state["scope"], state["binding"]["frozen_input_id"], "prepared-id", digest
    )


def test_read_transaction_closes_before_original_io_and_internal_receipt_has_no_private_repr(ports):
    receipt = verify(ports)
    assert ports["events"] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "load",
        "original-io",
    ]
    assert "private" not in repr(receipt)
    assert receipt.digest == "prepared-sha" and receipt.input_id == "prepared-id"


def test_wrong_prepared_digest_prevents_original_io(ports):
    with pytest.raises(DomainError) as error:
        verify(ports, "different")
    assert error.value.code == "PACKAGE_EXECUTION_INPUT_CHANGED"
    assert "original-io" not in ports["events"]


@pytest.mark.parametrize("part", ["facts", "head", "document", "binding", "flags"])
def test_new_context_cannot_replace_saved_prepared_snapshot(ports, part):
    def mutate():
        s = ports["snapshot"]
        if part == "facts":
            s["context"]["manifest"]["facts"]["value"] = "new-value"
        elif part == "head":
            s["observations"]["head"] = "new-head"
        elif part == "document":
            s["documents"][0]["parse_id"] = "new-parse"
        elif part == "binding":
            s["binding"]["input_digest"] = "a" * 64
        else:
            s["result"]["blockers"] = []
            s["result"].update(
                review_ready=True, launch_available=True, publication_authorized=True
            )

    ports["during_verify"] = mutate
    with pytest.raises(DomainError) as error:
        verify(ports)
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"


def test_observation_time_changes_are_not_new_semantic_inputs(ports):
    s = ports["snapshot"]
    s["context"]["manifest"]["as_of"] = "new"
    s["context"]["snapshot_digest"] = "new"
    s["result"]["checked_at"] = "new"
    s["result"]["current_context"].update(as_of="new", snapshot_digest="new")
    verify(ports)


def test_publication_reloads_prepared_under_ordered_locks_and_still_rejects_qualification(ports):
    receipt = verify(ports)
    ports["events"].clear()
    with pytest.raises(DomainError) as error:
        prepared.recheck_for_publication(ports["connection"](), receipt)
    assert error.value.code == "PACKAGE_REVIEW_EXECUTION_BLOCKED"
    assert ports["events"] == ["bid-lock", "graph-lock", "load"]


def test_late_context_change_and_replaced_prepared_record_do_not_publish(ports):
    receipt = verify(ports)
    ports["snapshot"]["observations"]["head"] = "changed"
    with pytest.raises(DomainError) as error:
        prepared.recheck_for_publication(ports["connection"](), receipt)
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"
    original = ports["packet"]
    changed = original.snapshot()
    changed["documents"] = []
    ports["packet"] = PreparedExecutionInput(
        original.scope,
        original.frozen_id,
        original.input_id,
        original.digest,
        original._view_text,
        json.dumps(changed),
    )
    with pytest.raises(DomainError) as error:
        prepared.recheck_for_publication(ports["connection"](), receipt)
    assert error.value.code == "PACKAGE_EXECUTION_INPUT_CHANGED"


def test_autocommit_rejected_before_locks_or_reads(ports):
    receipt = verify(ports)
    c = ports["connection"]()
    c.autocommit = True
    ports["events"].clear()
    with pytest.raises(ValueError):
        prepared.recheck_for_publication(c, receipt)
    assert not ports["events"]


def test_packet_defensive_copies_keep_private_context_and_rerun_identity(ports):
    packet = ports["packet"]
    copy = packet.snapshot()
    copy["context"]["manifest"]["facts"].clear()
    view = packet.view()
    view["manifest"]["identity"]["binding"].clear()
    assert packet.snapshot()["context"]["manifest"]["facts"]["value"] == "private-fact"
    assert packet.view()["manifest"]["identity"]["binding"] == ports["binding"]
    assert "private" not in repr(packet)
    rerun = {"nonce": "00000000-0000-4000-8000-000000000099", "reason": "explicit rerun"}
    changed = packet.view()
    changed["manifest"]["identity"] = identify(ports["binding"], rerun)
    ports["packet"] = PreparedExecutionInput(
        packet.scope,
        packet.frozen_id,
        packet.input_id,
        packet.digest,
        json.dumps(changed),
        packet._snapshot_text,
    )
    receipt = verify(ports)
    assert receipt._originals.execution_identity(rerun) == changed["manifest"]["identity"]
