"""Closed independent contracts and pagination invariants without a database."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import FastAPI

from apps.api.authoring_input_catalog_routes import router
from packages.authoring.content import empty_content
from packages.authoring_input_catalog import policy
from packages.contracts import authoring_input_catalog_api as contract
from packages.domain.runtime import DomainError, sha


def uid():
    return str(uuid4())


def test_three_closed_read_only_contract_roots_and_required_exact_queries():
    app = FastAPI()
    app.include_router(router)
    document = app.openapi()
    contract.extend_openapi(document)
    assert set(document["paths"]) == set(contract.ROOTS)
    for path, (name, _) in contract.ROOTS.items():
        assert set(document["paths"][path]) == {"get"}
        assert document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == contract.ref(name)
        assert contract.SCHEMAS[name]["additionalProperties"] is False
    params = document["paths"][contract.FACTS_PATH]["get"]["parameters"]
    assert {item["name"] for item in params if item["in"] == "query" and item["required"]} == {
        "expected_fact_set_digest",
        "fact_head_revision",
        "target_package_id",
        "target_revision_id",
        "target_manifest_digest",
        "authority_package_id",
        "authority_revision_id",
        "authority_manifest_digest",
    }


def test_node_projection_is_closed_full_body_with_no_qualification():
    content = empty_content("Explicit synthetic node", 7)
    target = {
        key: uid() for key in ("draft_id", "snapshot_id", "section_id", "section_revision_id")
    }
    target.update({key: "a" * 64 for key in ("snapshot_digest", "section_digest", "schema_digest")})
    target.update(base_draft_revision=1, base_section_revision=1)
    value = policy.marker(
        {
            "protocol": "package-authoring-node-catalog/1",
            "bid_id": uid(),
            "target": target,
            "section_title": content["attrs"]["title"],
            "section_content": content,
            "nodes": [],
            "unsupported_stable_node_count": 0,
            "current_draft_revision": 1,
            "section_heads": [
                {"section_id": target["section_id"], "selected_revision": 1, "head_revision": 1}
            ],
            "whole_snapshot_plain": True,
            "structure_supported": True,
            "blocking_reasons": [],
        },
        "2026-10-21T00:00:00+00:00",
    )
    assert contract.checked("PackageAuthoringNodeCatalog", value) == value
    for key, replacement in (
        ("admission_granted", True),
        ("unrequested", True),
        ("formal_decisions_allowed", True),
    ):
        bad = deepcopy(value)
        bad[key] = replacement
        with pytest.raises(DomainError, match="不能核验"):
            contract.checked("PackageAuthoringNodeCatalog", bad)


def test_page_pins_entire_observation_scope_and_does_not_depend_on_time(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "synthetic-catalog-test")
    items = [{"id": str(uuid4())} for _ in range(3)]
    items.sort(key=lambda row: row["id"])
    kwargs = {
        "identity": "id",
        "scope": {"bid_id": uid()},
        "limit": 1,
        "at": "2026-10-21T00:00:00Z",
    }
    first = policy.page({"head": 1}, items, cursor=None, **kwargs)
    next_page = policy.page(
        {"head": 1}, items, cursor=first["next_cursor"], **{**kwargs, "at": "2026-10-22T00:00:00Z"}
    )
    assert next_page["items"] == [items[1]]
    assert first["observation_digest"] == next_page["observation_digest"]
    with pytest.raises(DomainError) as changed:
        policy.page({"head": 2}, items, cursor=first["next_cursor"], **kwargs)
    assert changed.value.code.endswith("OBSERVATION_CHANGED")
    with pytest.raises(DomainError) as wrong:
        policy.page(
            {"head": 1},
            items,
            cursor=first["next_cursor"],
            **{**kwargs, "scope": {"bid_id": uid()}},
        )
    assert wrong.value.code.endswith("CURSOR_INVALID")
    with pytest.raises(DomainError):
        policy.page({"head": 1}, items, cursor=first["next_cursor"] + "x", **kwargs)


@pytest.mark.parametrize("value", [None, "", "A" * 64, True, sha(b"synthetic") + "x"])
def test_expected_digest_never_defaults(value):
    with pytest.raises(DomainError) as error:
        policy.request_digest(value)
    assert error.value.status == 422
