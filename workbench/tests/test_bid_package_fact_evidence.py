"""Port coordination tests; real privileges and exact parse reads have PG acceptance."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from packages.domain import bid_package_fact_evidence as service
from packages.domain.package_fact_evidence import select
from packages.domain.package_review_frozen_input import FrozenPackageReviewInput
from packages.domain.runtime import DomainError
from packages.rag.indexing import original_source_id
from tests.test_package_fact_evidence import packet  # noqa: F401
from tests.test_package_fact_scope import uid


@pytest.fixture
def ports(packet, monkeypatch):  # noqa: F811
    root = packet.evidence()
    member = dict(document_version_id=uid(10), parse=dict(parse_run_id=uid(11)))
    root["selection"] = {
        role: {"manifest": {"members": [member] if role == "target" else []}}
        for role in ("target", "authority")
    }
    packet = FrozenPackageReviewInput(packet._manifest_text, json.dumps(root), packet.digest)
    selection = select(packet, packet.digest, [uid(12)]).view()
    ref = selection["selected"][0]
    closure = [
        dict(
            source_id=ref["source_id"],
            id=ref["source_id"],
            document_version_id=uid(10),
            digest="a" * 64,
            revision=2,
            kind="document",
            policy_class="prebid_content",
            known_at="2026-10-19T00:00:00+00:00",
            status="published",
            valid_from="2026-10-19T00:00:00+00:00",
            valid_until=None,
        )
    ]
    closure.append(closure[0] | {"id": str(original_source_id(UUID(uid(10))))})
    calls = []
    monkeypatch.setattr(service, "require_read_committed", lambda c: calls.append("rc"))
    monkeypatch.setattr(service, "lock_bid", lambda c, bid: calls.append("bid"))
    monkeypatch.setattr(service, "assert_work_writable", lambda c, bid: calls.append("writable"))
    monkeypatch.setattr(service, "lock_graph", lambda c: calls.append("graph"))
    monkeypatch.setattr(service.inputs, "load_input", lambda *args: packet)
    monkeypatch.setattr(
        service, "read_member", lambda c, bid, m: calls.append(m["parse"]["parse_run_id"])
    )
    monkeypatch.setattr(service, "source_closure", lambda *args, **kw: closure)
    c = SimpleNamespace(
        autocommit=False,
        execute=lambda query, *args: SimpleNamespace(
            fetchone=lambda: None
            if "FROM design.document_relations" in query
            else dict(at=datetime(2026, 10, 20, tzinfo=timezone.utc))
        ),
    )
    scope = tuple(
        packet.view()["manifest"][key]
        for key in ("bid_id", "package_id", "revision_id", "inventory_id")
    )
    return c, scope, packet, closure, calls


def read(case):
    c, scope, frozen_packet, closure, calls = case
    return service.read_basis(c, scope, uid(5), frozen_packet.digest, [uid(12)])


def test_caller_retains_transaction_and_exact_basis_is_defensive(ports):
    result = read(ports)
    assert ports[4] == ["rc", "bid", "writable", "graph", uid(11)]
    assert result.basis()["references"][0]["source_revision"] == 2
    basis = result.basis()
    basis["references"].clear()
    assert result.basis()["references"]
    closure = result.closure()
    closure[0]["status"] = "withdrawn"
    assert result.closure()[0]["status"] == "published"
    assert "basis_text" not in repr(result)
    assert all(
        result.view()[key] is False
        for key in (
            "original_bytes_verified",
            "facts_qualified",
            "review_ready",
            "launch_available",
            "publication_authorized",
        )
    )


@pytest.mark.parametrize(
    "change",
    [
        "withdrawn",
        "future",
        "expired",
        "official",
        "version",
        "digest",
        "no_self",
        "duplicate_self",
        "missing_original",
        "extra_parent",
        "foreign_original",
    ],
)
def test_bad_current_source_never_conveys_fact_authority(ports, change):
    row = ports[3][0]
    if change == "withdrawn":
        row["status"] = "withdrawn"
    if change == "future":
        row["known_at"] = "2026-10-21T00:00:00+00:00"
    if change == "expired":
        row["valid_until"] = "2026-10-19T12:00:00+00:00"
    if change == "official":
        row["policy_class"] = "official_label"
    if change == "version":
        row["document_version_id"] = uid(999)
    if change == "digest":
        row["digest"] = "0" * 64
    if change == "no_self":
        row["id"] = uid(999)
    if change == "duplicate_self":
        ports[3].append(dict(row))
    if change == "missing_original":
        ports[3].pop()
    if change == "extra_parent":
        ports[3].append(row | {"id": uid(999)})
    if change == "foreign_original":
        ports[3][1]["document_version_id"] = uid(999)
    with pytest.raises(DomainError):
        read(ports)


def test_autocommit_is_rejected_before_any_lock_or_read(ports):
    ports[0].autocommit = True
    with pytest.raises(ValueError):
        read(ports)
    assert ports[4] == []
