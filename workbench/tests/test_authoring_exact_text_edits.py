"""Human edits reconstruct from immutable content, never caller source metadata."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.authoring.content import empty_content
from packages.authoring.exact_text_edits import materialize
from packages.domain.runtime import DomainError, sha


def sample():
    content = empty_content("Synthetic section", 0)
    content["attrs"]["rule_ids"] = [str(uuid4())]
    content["attrs"]["source_refs"] = [
        {
            "source_id": str(uuid4()),
            "source_revision": 3,
            "evidence_id": str(uuid4()),
            "document_version_id": str(uuid4()),
        }
    ]
    node = content["content"][0]
    node["content"] = [{"type": "text", "text": "original"}]
    content["content"].append(
        {
            "type": "heading",
            "attrs": {"id": str(uuid4()), "level": 2},
            "content": [{"type": "text", "text": "Sibling title"}],
        }
    )
    request = {
        "base_draft_revision": 2,
        "section_revision_id": str(uuid4()),
        "node_id": node["attrs"]["id"],
        "before_node_digest": sha(node),
        "replacement_text": "New literal <script>字符</script>\n第二行",
        "reason": "Synthetic wording correction",
    }
    return content, request


@pytest.mark.parametrize("replacement", ["Human text 人工", "", "a\nb\t$() <b>literal</b>"])
def test_preserves_metadata_structure_siblings_and_input(replacement):
    content, body = sample()
    before = deepcopy(content)
    body["replacement_text"] = replacement
    result = materialize(content, body)
    assert content == before
    assert result["attrs"] == before["attrs"]
    assert result["content"][1:] == before["content"][1:]
    assert result["content"][0]["attrs"] == before["content"][0]["attrs"]
    assert result["content"][0]["content"] == (
        [{"type": "text", "text": replacement}] if replacement else []
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "digest",
        "id",
        "nochange",
        "controls",
        "reason",
        "mark",
        "break",
        "duplicate",
        "rich",
        "list",
    ],
)
def test_unsupported_or_stale_edit_rejects(mutation):
    content, body = sample()
    if mutation == "digest":
        body["before_node_digest"] = "0" * 64
    elif mutation == "id":
        body["node_id"] = "missing"
    elif mutation == "nochange":
        body["replacement_text"] = "original"
    elif mutation == "controls":
        body["replacement_text"] = "bad\x00"
    elif mutation == "reason":
        body["reason"] = "  \n"
    elif mutation == "mark":
        content["content"][0]["content"][0]["marks"] = [{"type": "bold"}]
    elif mutation == "break":
        content["content"][0]["content"].append({"type": "hardBreak"})
    elif mutation == "duplicate":
        content["content"].append(deepcopy(content["content"][0]))
    elif mutation == "rich":
        content["content"][0]["type"] = "table"
    else:
        content["content"][0]["type"] = "bulletList"
        content["content"][0]["content"] = []
    if mutation in {"mark", "break", "list"}:
        body["before_node_digest"] = sha(content["content"][0])
    before = deepcopy(content)
    with pytest.raises(DomainError):
        materialize(content, body)
    assert content == before


@pytest.mark.parametrize("field", ["source_refs", "rule_ids", "origin", "candidate_adopted"])
def test_caller_cannot_add_authority_fields(field):
    content, body = sample()
    body[field] = []
    with pytest.raises(ValidationError):
        materialize(content, body)


def test_text_length_is_bounded():
    content, body = sample()
    body["replacement_text"] = "界" * 20001
    with pytest.raises(ValidationError):
        materialize(content, body)


def batch_sample():
    content, one = sample()
    edits = [
        {
            "node_id": node["attrs"]["id"],
            "before_node_digest": sha(node),
            "replacement_text": f"Synthetic edited node {index}",
        }
        for index, node in enumerate(content["content"])
    ]
    body = {key: one[key] for key in ("base_draft_revision", "section_revision_id", "reason")}
    return content, {**body, "protocol": "authoring-exact-multi-text-edit/1", "edits": edits}


def test_batch_preserves_original_structure_and_all_source_metadata():
    content, body = batch_sample()
    original = deepcopy(content)
    result = materialize(content, body)
    assert content == original
    assert result["attrs"] == original["attrs"]
    for index, node in enumerate(result["content"]):
        assert node["attrs"] == original["content"][index]["attrs"]
        assert node["content"] == [
            {"type": "text", "text": body["edits"][index]["replacement_text"]}
        ]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "stale",
        "nochange",
        "controls",
        "marked",
        "metadata",
        "one",
        "many",
        "total",
        "protocol",
    ],
)
def test_batch_rejects_every_invalid_item_without_partial_changes(mutation):
    content, body = batch_sample()
    last = body["edits"][-1]
    if mutation == "duplicate":
        body["edits"][-1] = deepcopy(body["edits"][0])
    elif mutation == "missing":
        last["node_id"] = "foreign-or-missing-node"
    elif mutation == "stale":
        last["before_node_digest"] = "0" * 64
    elif mutation == "nochange":
        last["replacement_text"] = "Sibling title"
    elif mutation == "controls":
        last["replacement_text"] = "bad\x00"
    elif mutation == "marked":
        content["content"][-1]["content"][0]["marks"] = [{"type": "bold"}]
        last["before_node_digest"] = sha(content["content"][-1])
    elif mutation == "metadata":
        last["source_refs"] = []
    elif mutation == "one":
        body["edits"] = body["edits"][:1]
    elif mutation == "many":
        body["edits"] *= 11
    elif mutation == "total":
        for edit in body["edits"]:
            edit["replacement_text"] = "字" * 10001
    else:
        body["protocol"] = "authoring-exact-multi-text-edit/unknown"
    original = deepcopy(content)
    with pytest.raises((DomainError, ValidationError)):
        materialize(content, body)
    assert content == original
