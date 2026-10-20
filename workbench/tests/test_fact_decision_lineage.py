"""Multiple explicit set carryovers must still resolve the original confirmed decision."""

import json
from types import SimpleNamespace

import pytest

from packages.domain import bid_package_fact_provenance as provenance
from packages.domain.fact_sets import identity
from packages.domain.runtime import sha


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


@pytest.fixture
def chain(monkeypatch):
    facts = {
        uid(n): {
            "id": uid(n),
            "bid_id": uid(9),
            "fact_set_id": uid(20 + n),
            "subject": "本工程",
            "scope": "本标段",
            "name": "工期",
            "value_jsonb_text": '"180"',
            "unit": "天",
            "evidence_ids": [],
        }
        for n in range(3)
    }
    basis = {
        "fact_identity": identity({**facts[uid(0)], "value": "180"}),
        "evidence": {"references": [], "source_closure_digest": sha([])},
    }
    edges = {
        uid(n): {
            "new_fact_id": uid(n),
            "from_fact_id": uid(n - 1),
            "from_decision_id": uid(30),
            "equivalence_digest": sha(basis),
            "audit_id": uid(40 + n),
            "audit_digest": "a" * 64,
            "bid_id": uid(9),
            "audit_recorded_at": "2026-10-19T00:00:00.000000Z",
            "actor_id": uid(50),
            "command_id": None,
            "fact_set_id": uid(20 + n),
            "previous_set_id": uid(19 + n),
            "previous_set_recorded": True,
        }
        for n in (1, 2)
    }
    monkeypatch.setattr(provenance, "_carryover", lambda c, bid, fact: edges.get(fact["id"]))
    monkeypatch.setattr(
        provenance, "_fact", lambda c, bid, fact_id: facts.get(fact_id), raising=False
    )
    c = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: []))
    item = {
        "fact": facts[uid(2)],
        "decision": {
            "id": uid(30),
            "bid_id": uid(9),
            "object_kind": "fact",
            "object_id": uid(0),
            "decision": "confirmed",
            "created_at": "2026-10-18T00:00:00.000000Z",
        },
        "decision_basis_jsonb_text": json.dumps(basis),
        "scope_binding": "unproven",
    }
    return c, item, facts, edges, basis


def test_two_audited_carryovers_bind_the_original_decision(chain):
    c, item, facts, edges, basis = chain
    proof = provenance.read_proof(c, uid(9), item, "2026-10-20T00:00:00.000000Z")
    assert proof["decision_binding"] is True
    assert [row["new_fact_id"] for row in proof["decision_lineage"]] == [uid(2), uid(1)]
    assert proof["version"] == "package-fact-provenance/2"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "bid",
        "set",
        "parent",
        "basis",
        "cycle",
        "future",
        "chronology",
        "value",
        "original_value",
        "decision_future",
    ],
)
def test_broken_explicit_lineage_cannot_invent_a_confirmation(chain, change):
    c, item, facts, edges, basis = chain
    if change == "missing":
        del edges[uid(1)]
    if change == "bid":
        edges[uid(1)]["bid_id"] = uid(999)
    if change == "set":
        edges[uid(1)]["fact_set_id"] = uid(999)
    if change == "parent":
        edges[uid(1)]["previous_set_id"] = uid(999)
    if change == "basis":
        edges[uid(1)]["equivalence_digest"] = "0" * 64
    if change == "cycle":
        edges[uid(1)]["from_fact_id"] = uid(2)
    if change == "future":
        edges[uid(1)]["audit_recorded_at"] = "2026-10-21T00:00:00.000000Z"
    if change == "chronology":
        edges[uid(2)]["audit_recorded_at"] = "2026-10-18T12:00:00.000000Z"
    if change == "value":
        facts[uid(1)]["value_jsonb_text"] = '"181"'
    if change == "original_value":
        facts[uid(0)]["value_jsonb_text"] = '"181"'
    if change == "decision_future":
        item["decision"]["created_at"] = "2026-10-21T00:00:00.000000Z"
    assert (
        provenance.read_proof(c, uid(9), item, "2026-10-20T00:00:00.000000Z")["decision_binding"]
        is False
    )


def test_explicit_edge_limit_fails_closed(chain):
    from packages.domain.fact_decision_lineage import resolve

    c, item, facts, edges, basis = chain
    assert (
        resolve(
            uid(9),
            item["fact"],
            item["decision"],
            basis,
            "2026-10-20T00:00:00.000000Z",
            lambda f: edges[f["id"]],
            facts.get,
            limit=1,
        )
        is None
    )
