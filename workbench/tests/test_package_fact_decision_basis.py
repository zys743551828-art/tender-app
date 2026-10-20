"""A decision needs one exact audit basis; newest-row ordering is not authority."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.domain import package_review_context as context
from tests.test_package_fact_scope import uid


@pytest.fixture
def audit_case(monkeypatch):
    decision = dict(
        id=uid(1),
        bid_id=uid(2),
        object_kind="fact",
        object_id=uid(3),
        actor_id=uid(4),
        decision="confirmed",
        created_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )
    fact = dict(id=uid(3), bid_id=uid(2), fact_set_id=uid(5), evidence_ids=[])
    basis = dict(
        basis_jsonb_text='{"fact_identity":"synthetic"}',
        actor_id=uid(4),
        payload=dict(
            decision_id=uid(1), object_kind="fact", object_id=uid(3), decision="confirmed"
        ),
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
        not_future=True,
    )
    audits = [basis]
    monkeypatch.setattr(context, "current_decision", lambda *args: decision)

    def execute(query, params=None):
        rows = (
            [dict(fact_set_id=uid(5), revision=1, fact_set_digest="a" * 64)]
            if "FROM design.fact_heads" in query
            else [fact]
            if "FROM design.fact_items" in query
            else audits
            if "FROM design.audit_entries" in query
            else []
        )
        return SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: rows[0] if rows else None)

    c = SimpleNamespace(execute=execute)
    return c, decision, basis, audits


def test_duplicate_decision_basis_does_not_pick_the_newest(audit_case):
    c, decision, basis, audits = audit_case
    audits.append(dict(basis))
    assert context.read_facts(c, uid(2), set())["items"][0]["decision_basis_jsonb_text"] is None


def test_one_exact_audit_basis_is_retained_without_changing_context_shape(audit_case):
    c, decision, basis, audits = audit_case
    result = context.read_facts(c, uid(2), set())
    assert result["items"][0]["decision_basis_jsonb_text"] == basis["basis_jsonb_text"]
    assert (
        result["version"] == "package-review-facts/1" and result["qualification"] == "not_validated"
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "actor",
        "decision",
        "object_id",
        "object_kind",
        "malformed",
        "future",
        "before_decision",
        "bid",
    ],
)
def test_ambiguous_or_mismatched_basis_is_unproven(audit_case, change):
    c, decision, basis, audits = audit_case
    if change == "missing":
        audits.clear()
    if change == "actor":
        basis["actor_id"] = uid(999)
    if change in {"decision", "object_id", "object_kind"}:
        basis["payload"][change] = "wrong"
    if change == "malformed":
        basis["payload"] = []
    if change == "future":
        basis["not_future"] = False
    if change == "before_decision":
        basis["created_at"] = datetime(2026, 10, 17, tzinfo=timezone.utc)
    if change == "bid":
        decision["bid_id"] = uid(999)
    assert context.read_facts(c, uid(2), set())["items"][0]["decision_basis_jsonb_text"] is None
