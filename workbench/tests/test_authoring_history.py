"""Closed historical DTO and precise original selection; no paid/runtime I/O."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.authoring.content import empty_content, schema_digest_for
from packages.authoring_history import service
from packages.contracts import authoring_history_api as contract
from packages.domain.runtime import DomainError, sha


def value():
    content = empty_content("历史章节", 7)
    content["content"][0]["content"] = [{"type": "text", "text": "完整历史原文" * 1000}]
    return {
        "version": "authoring-historical-section/1",
        **{
            key: str(uuid4())
            for key in ("bid_id", "draft_id", "section_id", "section_revision_id", "created_by")
        },
        "revision": 2,
        "schema_digest": schema_digest_for(content),
        "digest": sha(content),
        "content": content,
        "created_at": "2026-10-21T10:00:00Z",
        "images": [],
        "read_only": True,
        "source_qualification_assessed": False,
        "restoration_authorized": False,
    }


def test_closed_read_schema_preserves_original_sparse_ordinal_and_body():
    original = value()
    assert contract.checked(original) is original
    changed = deepcopy(original)
    changed["content"]["attrs"]["ordinal"] = 500
    with pytest.raises(DomainError):
        contract.checked(changed)


@pytest.mark.parametrize(
    "field", ["read_only", "source_qualification_assessed", "restoration_authorized"]
)
def test_read_does_not_grant_mutation_or_source_qualification(field):
    original = value()
    original[field] = not original[field]
    with pytest.raises(DomainError):
        contract.checked(original)


@pytest.mark.parametrize("where", ["root", "content", "metadata"])
def test_unknown_fields_rejected(where):
    original = value()
    target = (
        original
        if where == "root"
        else original["content"]
        if where == "content"
        else original["content"]["attrs"]
    )
    target["unexpected"] = "must not silently lose original content"
    with pytest.raises(DomainError):
        contract.checked(original)


@pytest.mark.parametrize("bad", [None, "", "a" * 63, "A" * 64, True])
def test_expected_digest_is_required_before_any_database_read(monkeypatch, bad):
    monkeypatch.setattr(service, "snapshot", lambda: pytest.fail("invalid request reached DB"))
    with pytest.raises(DomainError) as error:
        service.resolve(*(str(uuid4()) for _ in range(3)), 1, expected_digest=bad)
    assert error.value.status == 422


def test_opt_in_export_does_not_advertise_unmounted_route_or_edit_other_schemas():
    document = {"paths": {}, "components": {"schemas": {"SectionView": {"sentinel": True}}}}
    contract.extend_openapi(document)
    assert document["components"]["schemas"] == {"SectionView": {"sentinel": True}}
    document["paths"][contract.PATH] = {"get": {"responses": {}}}
    contract.extend_openapi(document)
    assert document["components"]["schemas"]["SectionView"] == {"sentinel": True}
    assert document["paths"][contract.PATH]["get"]["security"] == [{"SessionCookie": []}]
