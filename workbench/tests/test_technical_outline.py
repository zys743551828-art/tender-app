"""Current outline source admission, replay and deterministic append-only changes."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api import authoring_structure as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.authoring import structure_repository as structures
from packages.authoring import technical_outline as outline
from packages.authoring.content import empty_content
from packages.authoring.structure_model import mutate, node
from packages.domain.runtime import DomainError, now, sha

BID, DRAFT, ACTION, ACTOR, TARGET, SOURCE, OWN_REV, SOURCE_REV, INV, RULE, DECISION = [
    str(UUID(int=i)) for i in range(1, 12)
]
BASIS = {
    "target": {"package_id": TARGET, "revision_id": OWN_REV, "digest": "a" * 64},
    "authority": {"package_id": SOURCE, "revision_id": SOURCE_REV, "digest": "b" * 64},
    "inventory": {"id": INV, "digest": "c" * 64},
}
REQUEST = {"base_draft_revision": 5, "basis": BASIS, "chapter_keys": ["quality", "schedule"]}
PATH = f"/api/v1/bids/{BID}/drafts/{DRAFT}/technical-outline/preview"


def binding():
    return {
        "rule_id": RULE,
        "decision_id": DECISION,
        "decision_snapshot": {"decision": "confirmed"},
        "annotation": {"mapped": True},
        "source_bound": True,
        "rule_snapshot": {
            "provenance_status": "effective",
            "evidence_ids": [str(UUID(int=98))],
            "statement": "工期、质量要求须核对",
        },
        "requirement": {"categories": ["technical"], "applicability": "applicable"},
    }


@pytest.fixture
def facts(monkeypatch):
    frozen_sources = [{"id": "source", "revision": 1}]
    manifest = {
        "package_digest": BASIS["target"]["digest"],
        "authority_digest": BASIS["authority"]["digest"],
        "authority_revision_id": SOURCE_REV,
        "rule_set_id": str(UUID(int=97)),
        "rule_set_digest": "d" * 64,
        "identity_digest": "e" * 64,
        "source_snapshot": deepcopy(frozen_sources),
        "requirements": [binding()],
    }
    args = SimpleNamespace(
        target=SimpleNamespace(revision_id=OWN_REV, manifest_digest=BASIS["target"]["digest"]),
        source=SimpleNamespace(
            package_id=SOURCE, revision_id=SOURCE_REV, manifest_digest=BASIS["authority"]["digest"]
        ),
        identity={"digest": manifest["identity_digest"]},
        rules={"digest": manifest["rule_set_digest"]},
        sources=frozen_sources,
        head=deepcopy(BASIS["inventory"]),
        inventory={"manifest": manifest, "digest": BASIS["inventory"]["digest"]},
        decision={"id": UUID(DECISION), "decision": "confirmed"},
        calls=[],
    )

    def load(_c, bid, target, revision, inventory):
        assert (bid, target, revision, inventory) == (BID, TARGET, OWN_REV, INV)
        args.calls.append("inventory")
        return args.inventory

    def context(_c, bid, target, revision, authority, rule_set):
        assert (bid, target, revision, authority, rule_set) == (
            BID,
            TARGET,
            OWN_REV,
            SOURCE_REV,
            manifest["rule_set_id"],
        )
        args.calls.append("context")
        return args.target, args.source, args.identity, args.rules, args.sources

    def head(_c, revision, *, lock):
        assert revision == OWN_REV and lock
        args.calls.append("locked-head")
        return args.head

    monkeypatch.setattr(outline.requirements, "load_inventory", load)
    monkeypatch.setattr(outline.requirements, "_context", context)
    monkeypatch.setattr(outline.requirements, "head", head)
    monkeypatch.setattr(outline, "current_decision", lambda *_a: args.decision)
    return args


def test_locks_selected_inventory_and_appends_only_supported_nonduplicate_chapters(facts):
    captured = outline.capture(None, UUID(BID), BASIS)
    assert captured.suggested == ("schedule", "quality")
    assert facts.calls == ["inventory", "context", "locked-head"]
    identity = str(UUID(int=99))
    state = {"nodes": [node(identity)]}
    contents = {identity: empty_content("施工进度与资源配置", 0)}
    changes = outline.build_changes(state, contents, REQUEST["chapter_keys"], captured)
    assert len(changes) == 1 and changes[0]["ordinal"] == 1
    result = mutate(state["nodes"], contents, changes)
    new = result["contents"][result["nodes"][-1]["section_id"]]
    assert contents[identity] == result["contents"][identity]
    assert new["attrs"] == {
        "title": "质量管理与验收",
        "ordinal": 1,
        "rule_ids": [],
        "source_refs": [],
    }
    assert len(new["content"]) == 1
    empty = new["content"][0]
    assert empty["type"] == "paragraph" and empty["content"] == [] and UUID(empty["attrs"]["id"])
    for rejected in (["safety"], ["quality", "quality"], ["schedule"]):
        with pytest.raises(DomainError):
            outline.build_changes(state, contents, rejected, captured)


@pytest.mark.parametrize(
    "side", ["target", "authority", "inventory", "sources", "rules", "decision"]
)
def test_changed_basis_cannot_be_confirmed(facts, side):
    stable = outline.capture(None, UUID(BID), BASIS)
    stored = {"basis": BASIS, "suggested_digest": sha(stable.suggested)}
    outline.verify_apply(None, UUID(BID), stored)
    if side == "target":
        facts.target.manifest_digest = "1" * 64
    if side == "authority":
        facts.source.package_id = str(UUID(int=96))
    if side == "inventory":
        facts.head = {"id": str(UUID(int=95)), "digest": "2" * 64}
    if side == "sources":
        facts.sources[0]["revision"] += 1
    if side == "rules":
        facts.rules = {"digest": "3" * 64}
    if side == "decision":
        facts.decision = {"id": UUID(int=94), "decision": "rejected"}
    with pytest.raises(DomainError) as error:
        outline.verify_apply(None, UUID(BID), stored)
    assert error.value.code == "TECHNICAL_OUTLINE_BASIS_STALE"


@pytest.mark.parametrize("disposition", ["fresh", "historical-unbound", "replay", "reject"])
def test_structure_resolve_never_applies_stale_outline_and_preserves_original_receipt(
    monkeypatch, disposition
):
    action = UUID(ACTION)
    revision = 5
    state, contents = {}, {}
    payload = {
        "kind": "authoring_structure",
        "draft_id": DRAFT,
        "before_digest": sha({"state": state, "contents": contents}),
        "created_ids": {
            f"technical-bid-{BASIS['inventory']['digest']}-quality": str(UUID(int=400))
        },
    }
    if disposition != "historical-unbound":
        payload["technical_outline"] = {"basis": BASIS, "suggested_digest": "9" * 64}
    original = {"state": "applied", "action_id": ACTION, "draft_revision": revision + 1}
    consumed = {"result": original} if disposition == "replay" else None
    events = []

    def query(sql, _params):
        if sql.startswith("INSERT INTO action_consumptions"):
            events.append("record")
        return SimpleNamespace(fetchone=lambda: consumed)

    def fetch(_c, sql, params):
        if sql.startswith("SELECT id FROM bids"):
            events.append("bid-lock")
            return {"id": UUID(BID)}
        events.append("action-lock")
        assert params == (action, UUID(BID))
        return {
            "payload": payload,
            "request_digest": sha(payload),
            "base_revision": revision,
            "expires_at": now() + timedelta(seconds=100),
        }

    def guard(*_args):
        events.append("basis-lock-and-check")
        raise DomainError("TECHNICAL_OUTLINE_BASIS_STALE", "变化", 409)

    c = SimpleNamespace(execute=query)
    monkeypatch.setattr(structures, "require_read_committed", lambda *_: None)
    monkeypatch.setattr(structures, "fetch", fetch)
    monkeypatch.setattr(structures, "lock_draft", lambda *_: {"revision": revision})
    monkeypatch.setattr(structures, "match", lambda *_: None)
    monkeypatch.setattr(structures, "load", lambda *_: (state, contents))
    monkeypatch.setattr(outline, "verify_apply", guard)
    monkeypatch.setattr(structures, "commit", lambda *_: pytest.fail("must not change the draft"))

    def resolve(decision):
        return structures.resolve(c, UUID(BID), action, UUID(ACTOR), UUID(int=90), decision, "tag")

    if disposition == "replay":
        assert resolve("confirm") == original
    elif disposition == "reject":
        assert resolve("reject")["state"] == "rejected"
    else:
        with pytest.raises(DomainError) as error:
            resolve("confirm")
        assert error.value.code == (
            "TECHNICAL_OUTLINE_PREVIEW_REQUIRED"
            if disposition == "historical-unbound"
            else "TECHNICAL_OUTLINE_BASIS_STALE"
        )
    assert (
        events
        == ["bid-lock", "action-lock"]
        + {
            "fresh": ["basis-lock-and-check"],
            "reject": ["record"],
            "replay": [],
            "historical-unbound": [],
        }[disposition]
    )


def test_exact_http_preview_rejects_custom_content_and_old_receipt_precedes_basis(monkeypatch):
    spec = "/api/v1/bids/{bid_id}/drafts/{draft_id}/technical-outline/preview"
    operation = implemented_openapi(app)["paths"][spec]["post"]
    assert operation["operationId"] == "previewTechnicalAuthoringOutline"
    assert operation["security"] == [{"SessionCookie": []}]
    client = TestClient(app)
    assert client.post(PATH, json=REQUEST).status_code == 401
    assert client.post(PATH, json={**REQUEST, "changes": []}).status_code == 422

    @contextmanager
    def connection():
        yield None

    receipt = {"body": {"action_id": ACTION}, "status": 201, "headers": {}}
    monkeypatch.setattr(routes, "auth", lambda *_: {"member_id": UUID(ACTOR)})
    monkeypatch.setattr(routes, "connection", connection)
    monkeypatch.setattr(routes, "begin_draft", lambda *args: SimpleNamespace(replay=receipt))
    monkeypatch.setattr(
        outline, "capture", lambda *_: pytest.fail("replay must precede live checks")
    )
    result = client.post(PATH, json=REQUEST)
    assert result.status_code == 201 and result.json() == receipt["body"]
    assert result.headers["Idempotent-Replayed"] == "true"
