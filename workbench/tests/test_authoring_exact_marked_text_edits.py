"""Synthetic B7 reconstruction tests, not real document acceptance."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.authoring import exact_text_edits
from packages.authoring.content import empty_content
from packages.domain.runtime import DomainError, sha


def sample():
    content = empty_content("Synthetic marked section", 0)
    content["attrs"]["rule_ids"] = [str(uuid4())]
    content["attrs"]["source_refs"] = [
        {
            "source_id": str(uuid4()),
            "source_revision": 1,
            "evidence_id": str(uuid4()),
            "document_version_id": str(uuid4()),
        }
    ]
    node = content["content"][0]
    node["content"] = [{"type": "text", "text": "Original", "marks": [{"type": "bold"}]}]
    request = {
        "protocol": "authoring-exact-marked-text-edit/1",
        "base_draft_revision": 2,
        "section_revision_id": str(uuid4()),
        "node_id": node["attrs"]["id"],
        "before_node_digest": sha(node),
        "replacement_text": "Human replacement",
        "reason": "Correction",
    }
    return content, request


def test_frozen_b5_still_rejects_marked_node():
    content, body = sample()
    body.pop("protocol")
    with pytest.raises(DomainError):
        exact_text_edits.materialize(content, body)


@pytest.mark.parametrize(
    "marks",
    [
        [{"type": "bold"}],
        [{"type": "italic"}],
        [{"type": "italic"}, {"type": "bold"}],
        [{"type": "bold"}, {"type": "italic"}],
    ],
)
@pytest.mark.parametrize("kind", ["paragraph", "heading"])
def test_preserves_only_text_change(marks, kind):
    from packages.authoring.exact_marked_text_edits import materialize

    content, body = sample()
    node = content["content"][0]
    node["type"] = kind
    if kind == "heading":
        node["attrs"]["level"] = 2
    node["content"][0]["marks"] = marks
    body["before_node_digest"] = sha(node)
    before = deepcopy(content)
    result = materialize(content, body)
    assert content == before
    expected = deepcopy(before)
    expected["content"][0]["content"][0]["text"] = body["replacement_text"]
    assert result == expected
    result["content"][0]["content"][0]["marks"].clear()
    assert content == before


@pytest.mark.parametrize(
    "text", ["", " ", "\t", "x\n", "x\r", "x\x00", "x\x1f", "x\x7f", "Original"]
)
def test_invalid_text(text):
    from packages.authoring.exact_marked_text_edits import materialize

    content, body = sample()
    body["replacement_text"] = text
    with pytest.raises((DomainError, ValidationError)):
        materialize(content, body)


@pytest.mark.parametrize(
    "mutation",
    ["digest", "plain", "empty_marks", "duplicate", "mixed", "break", "bad_mark", "attrs"],
)
def test_unsupported_or_malicious_parent(mutation):
    from packages.authoring.exact_marked_text_edits import materialize

    content, body = sample()
    node = content["content"][0]
    leaf = node["content"][0]
    if mutation == "plain":
        leaf.pop("marks")
    elif mutation == "empty_marks":
        leaf["marks"] = []
    elif mutation == "duplicate":
        leaf["marks"] *= 2
    elif mutation == "mixed":
        node["content"].append({"type": "text", "text": "other"})
    elif mutation == "break":
        node["content"].append({"type": "hardBreak"})
    elif mutation == "bad_mark":
        leaf["marks"] = [{"type": "bold", "attrs": {"onclick": "bad"}}]
    elif mutation == "attrs":
        node["attrs"]["source_refs"] = []
    body["before_node_digest"] = "0" * 64 if mutation == "digest" else sha(node)
    before = deepcopy(content)
    with pytest.raises(DomainError):
        materialize(content, body)
    assert content == before


@pytest.mark.parametrize(
    "field", ["marks", "content", "source_refs", "rule_ids", "preserved_marks_digest"]
)
def test_no_client_authority(field):
    from packages.authoring.exact_marked_text_edits import materialize

    content, body = sample()
    body[field] = []
    with pytest.raises(ValidationError):
        materialize(content, body)


@pytest.mark.parametrize(
    "protocol", [None, "authoring-exact-text-edit/1", "authoring-exact-marked-text-edit/2"]
)
def test_requires_explicit_protocol(protocol):
    from packages.authoring.exact_marked_text_edits import parse_request

    _, body = sample()
    if protocol is None:
        body.pop("protocol")
    else:
        body["protocol"] = protocol
    with pytest.raises(ValidationError):
        parse_request(body)


def test_missing_extension_fails_closed(monkeypatch):
    from packages.authoring import exact_marked_text_edits as module

    monkeypatch.setattr(module, "installed", lambda c: False)
    monkeypatch.setattr(exact_text_edits, "available", lambda c: pytest.fail("must short circuit"))
    assert not module.available(None)
    with pytest.raises(DomainError) as error:
        module.require_available(None)
    assert error.value.code == "AUTHORING_EXACT_TEXT_EDIT_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "parent_kind",
    [
        "model_candidate_adoption",
        "manual_text_edit",
        "manual_multi_text_edit",
        "manual_marked_text_edit",
    ],
)
def test_manifest_binds_preserved_marks_and_root(monkeypatch, parent_kind):
    from uuid import UUID

    from packages.authoring import exact_marked_text_edits as module
    from packages.authoring import exact_sources
    from packages.authoring.content import SCHEMA_DIGEST
    from packages.authoring.exact_marked_text_edit_contracts import (
        AuthoringExactMarkedTextEditResult,
    )

    original, request = sample()
    content = module.materialize(original, request)
    parent_id, root_id = str(uuid4()), str(uuid4())
    parent_digest, root_digest = sha("parent"), sha("root")
    parent = {
        "digest": parent_digest,
        "manifest": {
            "id": parent_id,
            "bid_id": str(uuid4()),
            "draft_id": str(uuid4()),
            "section_id": str(uuid4()),
            "section_revision_id": request["section_revision_id"],
            "section_revision": 2,
            "section_digest": sha(original),
            "input": {"id": str(uuid4()), "digest": sha("input"), "context_digest": sha("context")},
            "origin": {
                "kind": parent_kind,
                "root_qualification_id": root_id,
                "root_qualification_digest": root_digest,
            },
        },
    }
    admission = module.ExactMarkedManualEdit(
        command_id=uuid4(),
        actor_id=uuid4(),
        condition='"condition"',
        before_action={"request": request},
        parent_qualification_id=UUID(parent_id),
        parent_qualification_digest=parent_digest,
    )
    monkeypatch.setattr(
        module,
        "policy",
        lambda: {
            "protocol": "authoring-exact-text-edit-policy/3",
            "supported_content": "single_marked_text_leaf_preserve_marks",
            "source_sha256": {"test": sha("captured")},
        },
    )
    citations = []
    monkeypatch.setattr(exact_sources, "record_citations", lambda *args: citations.append(args))

    class Connection:
        def __init__(self):
            self.writes = []

        def execute(self, sql, params):
            self.writes.append((sql, params))

    connection = Connection()
    value = module.bind(connection, admission, parent, content, content, SCHEMA_DIGEST)
    manifest = value["manifest"]
    origin = manifest["origin"]
    assert origin["preserved_marks_digest"] == sha(original["content"][0]["content"][0]["marks"])
    assert origin["root_qualification_id"] == (
        parent_id if parent_kind == "model_candidate_adoption" else root_id
    )
    assert origin["root_qualification_digest"] == (
        parent_digest if parent_kind == "model_candidate_adoption" else root_digest
    )
    assert value["digest"] == sha(manifest)
    assert manifest["method_digest"] == sha(manifest["method"])
    assert manifest["source_refs_digest"] == sha(original["attrs"]["source_refs"])
    assert manifest["rule_ids_digest"] == sha(original["attrs"]["rule_ids"])
    assert manifest["candidate_adopted"] is False
    assert manifest["content_correctness_certified"] is False
    assert len(connection.writes) == len(citations) == 1
    AuthoringExactMarkedTextEditResult.model_validate(
        {
            "protocol": "authoring-exact-text-edit-result/3",
            "bid_id": manifest["bid_id"],
            "draft_id": manifest["draft_id"],
            "draft_revision": 3,
            "snapshot_id": str(uuid4()),
            "snapshot_digest": sha("snapshot"),
            "parent_section_revision_id": request["section_revision_id"],
            "section_revision_id": manifest["section_revision_id"],
            "section_digest": sha(content),
            "qualification": value,
        }
    )
    altered = deepcopy(content)
    altered["content"][0]["content"][0]["marks"] = [{"type": "italic"}]
    with pytest.raises(DomainError):
        module.bind(connection, admission, parent, content, altered, SCHEMA_DIGEST)
    assert len(connection.writes) == 1


@pytest.mark.parametrize(
    "spacing", ["\u00a0", "\u202f", "\u0085", "\ufeff", "\ufeff \ufeff  \ufeff"]
)
def test_unicode_blank_parity_without_rewriting_meaningful_text(spacing):
    from packages.authoring.exact_marked_text_edits import materialize

    content, body = sample()
    body["replacement_text"] = spacing
    with pytest.raises(DomainError) as error:
        materialize(content, body)
    assert error.value.code == "INVALID_REQUEST"
    meaningful = spacing + "Meaningful word" + spacing
    body["replacement_text"] = meaningful
    result = materialize(content, body)
    assert result["content"][0]["content"][0]["text"] == meaningful


@pytest.mark.parametrize(
    "spacing", ["\u00a0", "\u202f", "\u0085", "\ufeff", "\ufeff \ufeff  \ufeff"]
)
def test_unicode_blank_reason_parity_preserves_valid_reason(spacing):
    from packages.authoring.exact_marked_text_edits import materialize, parse_request

    content, body = sample()
    body["reason"] = spacing
    with pytest.raises(DomainError) as error:
        materialize(content, body)
    assert error.value.code == "INVALID_REQUEST"
    reason = spacing + "Meaningful reason\n\t" + spacing
    body["reason"] = reason
    materialize(content, body)
    assert parse_request(body)["reason"] == reason
    assert body["reason"] == reason


@pytest.mark.parametrize("reason", ["bad\x00", "bad\x1f", "bad\x7f"])
def test_marked_reason_disallows_c0_and_del(reason):
    from packages.authoring.exact_marked_text_edits import materialize

    content, body = sample()
    body["reason"] = reason
    with pytest.raises(DomainError) as error:
        materialize(content, body)
    assert error.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize("reason", ["word\t\n", "word\u0085", "word\u009f"])
def test_marked_reason_retains_tab_lf_and_c1_with_meaningful_word(reason):
    from packages.authoring.exact_marked_text_edits import materialize, parse_request

    content, body = sample()
    body["reason"] = reason
    materialize(content, body)
    assert parse_request(body)["reason"] == reason


@pytest.mark.parametrize("missing", [None, "marked", "single", "multi", "manual"])
def test_installation_checks_every_private_dispatch_prerequisite(missing, monkeypatch):
    from packages.authoring import exact_marked_text_edits as module

    names = {
        "marked": "authoring_exact_check_marked_text_record",
        "single": "authoring_exact_check_single_text_record",
        "multi": "authoring_exact_check_multi_text_record",
        "manual": "authoring_exact_check_manual_record",
    }

    class Connection:
        def execute(self, query):
            for name in names.values():
                assert f"to_regprocedure('design.{name}(uuid)') IS NOT NULL" in query
            assert query.count("AND ") == 3
            return self

        def fetchone(self):
            return {"ready": missing is None}

    connection = Connection()
    monkeypatch.setattr(exact_text_edits, "available", lambda c: True)
    assert module.installed(connection) is (missing is None)
    assert module.available(connection) is (missing is None)
    if missing is not None:
        with pytest.raises(DomainError) as error:
            module.require_available(connection)
        assert error.value.code == "AUTHORING_EXACT_TEXT_EDIT_NOT_CONFIGURED"
