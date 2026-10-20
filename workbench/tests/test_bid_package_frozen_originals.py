"""Internal orchestration contracts with explicit snapshots; not database lock acceptance."""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from packages.domain import bid_package_frozen_originals as frozen
from packages.domain.runtime import DomainError

SCOPE = ("bid", "package", "revision", "inventory")


@pytest.fixture
def snapshots(monkeypatch):
    state = {"active": 0, "reads": 0, "calls": [], "during_io": None}
    result = {
        "kind": "eligibility_observation",
        "frozen_input_id": "input",
        "frozen_digest": "frozen-digest",
        "input_digest": "input-digest",
        "checked_at": "2026-10-20T00:00:00Z",
        "current_context": {
            "semantic_digest": "context",
            "snapshot_digest": "snapshot-1",
            "as_of": "2026-10-20T00:00:00Z",
            "facts_digest": "facts",
        },
        "parse_evidence_status": "matched",
        "original_verification": "not_performed",
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
        "blockers": ["PACKAGE_REVIEW_EXECUTOR_NOT_READY"],
    }
    state["snapshot"] = {
        "result": result,
        "observations": {"current": {"phase": "active"}, "sources": []},
        "documents": [
            {
                "package_role": role,
                "member_id": role,
                "document_version_id": "same-document",
                "parse_id": "exact-old-parse",
                "digest": "file-digest",
                "byte_size": 10,
                "object_key": "private-locator",
                "blocks": [{"text_content": "private-content"}],
            }
            for role in ("target", "authority")
        ],
    }

    class Connection:
        autocommit = False

        def execute(self, statement):
            assert "REPEATABLE READ, READ ONLY" in statement

    @contextmanager
    def connection():
        state["active"] += 1
        try:
            yield Connection()
        finally:
            state["active"] -= 1

    def capture(c, scope, input_id, digest):
        assert state["active"] == 1 and scope == SCOPE
        assert input_id == "input" and digest == "frozen-digest"
        state["reads"] += 1
        value = deepcopy(state["snapshot"])
        value["result"]["checked_at"] = f"2026-10-20T00:00:0{state['reads']}Z"
        value["result"]["current_context"]["as_of"] = value["result"]["checked_at"]
        value["result"]["current_context"]["snapshot_digest"] = str(state["reads"])
        return value

    def verify(document):
        assert state["active"] == 0
        state["calls"].append((document["package_role"], document["parse_id"]))
        if state["during_io"]:
            action, state["during_io"] = state["during_io"], None
            action()

    monkeypatch.setattr(frozen, "connection", connection)
    monkeypatch.setattr(frozen, "capture", capture)
    monkeypatch.setattr(frozen.original_verification, "verify", verify)
    return state


def verify():
    return frozen.verify(SCOPE, "input", "frozen-digest", "context")


def test_each_logical_use_keeps_exact_parse_and_io_has_no_connection(snapshots):
    receipt = verify()
    assert snapshots["calls"] == [("target", "exact-old-parse"), ("authority", "exact-old-parse")]
    assert snapshots["reads"] == 2 and snapshots["active"] == 0
    value = receipt.observation()
    assert value["original_verification"] == "verified_at_observation"
    assert not value["publication_authorized"] and not value["launch_available"]
    assert value["checked_at"] == "2026-10-20T00:00:02Z"
    assert "private" not in repr(receipt) and "private" not in str(value)
    value["originals"].clear()
    value["current_context"]["facts_digest"] = "caller-mutation"
    assert len(receipt.observation()["originals"]) == 2
    assert receipt.observation()["current_context"]["facts_digest"] == "facts"


@pytest.mark.parametrize("part", ["context", "source", "blocker", "document", "locator"])
def test_changed_inputs_across_io_never_produce_receipt(snapshots, part):
    def mutate():
        snapshot = snapshots["snapshot"]
        if part == "context":
            snapshot["result"]["current_context"]["facts_digest"] = "different"
        elif part == "source":
            snapshot["observations"]["sources"].append({"status": "withdrawn"})
        elif part == "blocker":
            snapshot["result"]["blockers"].append("PROJECT_WORK_CLOSED")
        elif part == "document":
            snapshot["documents"][0]["parse_id"] = "new-parse"
        else:
            snapshot["documents"][0]["object_key"] = "changed-locator"

    snapshots["during_io"] = mutate
    with pytest.raises(DomainError) as error:
        verify()
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"
    assert snapshots["active"] == 0


def test_wrong_context_prevents_provider_io(snapshots):
    with pytest.raises(DomainError) as error:
        frozen.verify(SCOPE, "input", "frozen-digest", "stale-context")
    assert error.value.code == "PACKAGE_REVIEW_CONTEXT_CHANGED"
    assert snapshots["calls"] == [] and snapshots["active"] == 0


def test_failed_provider_closes_snapshot_and_never_starts_second_snapshot(snapshots):
    def failure():
        raise DomainError("OBJECT_STORE_UNAVAILABLE", "synthetic unavailable", 503)

    snapshots["during_io"] = failure
    with pytest.raises(DomainError) as error:
        verify()
    assert error.value.code == "OBJECT_STORE_UNAVAILABLE"
    assert snapshots["reads"] == 1 and snapshots["active"] == 0


def test_publication_locks_bid_before_graph_and_refuses_readiness_shortcut(snapshots, monkeypatch):
    receipt = verify()
    events = []

    class Connection:
        autocommit = False

    c = Connection()
    monkeypatch.setattr(frozen, "lock_bid", lambda conn, bid: events.append(("bid", conn, bid)))
    monkeypatch.setattr(frozen, "lock_graph", lambda conn: events.append(("graph", conn)))
    monkeypatch.setattr(frozen, "capture", lambda *args: deepcopy(snapshots["snapshot"]))
    with pytest.raises(DomainError) as error:
        frozen.recheck_for_publication(c, receipt)
    assert events == [("bid", c, "bid"), ("graph", c)]
    assert error.value.code == "PACKAGE_REVIEW_EXECUTION_BLOCKED"
    assert len(snapshots["calls"]) == 2
    c.autocommit = True
    events.clear()
    with pytest.raises(ValueError):
        frozen.recheck_for_publication(c, receipt)
    assert not events
