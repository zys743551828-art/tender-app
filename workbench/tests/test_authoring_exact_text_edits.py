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
