"""Closed saved-content and choice protocols without a database or provider."""

from copy import deepcopy
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from test_authoring_rich import cell, document, paragraph, row, table
from work_context_catalog_fixtures import catalog_app, openapi

from packages.contracts import work_context_catalog_api as contract
from packages.domain.runtime import DomainError
from packages.work_contexts import authoring_repository, authoring_service


def test_actual_rich_text_schema_keeps_full_long_body_table_and_fixed_image_without_locators():
    text = "完整保存的长正文不能摘要替换。" * 15000
    content = document(paragraph(text))
    content["content"].append(table(row(cell(2, 2), cell()), row(cell())))
    image = {
        "type": "image",
        "attrs": {
            "id": uuid4().hex,
            "asset_id": str(uuid4()),
            "asset_revision": 1,
            "asset_version_id": str(uuid4()),
            "width_twips": 2400,
            "height_twips": 2400,
            "alt": "明确图片",
            "caption": "图片标题",
        },
    }
    content["content"].append(image)
    name = "WorkContextReadOnlyAuthoringRichDocument"
    assert contract.valid(name, content)
    assert content["content"][0]["content"][0]["text"] == text
    for key in ("object_key", "url", "private_request"):
        bad = deepcopy(content)
        bad["content"][-1]["attrs"][key] = "private/locator"
        assert not contract.valid(name, bad)


@pytest.mark.parametrize("state", ["pending", "failed", "not_published"])
def test_absent_or_failed_output_never_gets_a_downloadable_document(state):
    value = {"format": "pdf", "requested": True, "state": state, "document": None, "gaps": []}
    assert contract.valid("WorkContextBuildOutput", value)
    value["document"] = {
        "document_version_id": str(uuid4()),
        "sha256": "a" * 64,
        "byte_size": 1,
        "media_type": "application/pdf",
        "publication_proof_digest": "b" * 64,
    }
    assert not contract.valid("WorkContextBuildOutput", value)
    value["state"] = "succeeded"
    assert contract.valid("WorkContextBuildOutput", value)
    value["document"] = None
    assert not contract.valid("WorkContextBuildOutput", value)


def test_zero_section_saved_document_is_explicit_and_formal_summary_stays_unknown():
    assert contract.valid(
        "WorkContextSnapshotDocument",
        {"sections": [], "outline": [], "images": [], "editable": False},
    )
    value = {
        "perspective": "saved_authoring_history",
        "whole_package_blocking_risk_count": None,
        "whole_package_passed": None,
        "formal_scoring": {
            "status": "scope_not_selected",
            "scope_id": None,
            "numeric_prediction": None,
        },
        "official_labels_read": False,
        "primary_action": "open_selected_snapshot",
        "action_mode": "navigation_only",
    }
    assert contract.valid("WorkContextAuthoringSummary", value)
    for key in ("whole_package_blocking_risk_count", "whole_package_passed"):
        bad = value | {key: 0}
        assert not contract.valid("WorkContextAuthoringSummary", bad)
    value["formal_scoring"]["numeric_prediction"] = 0
    assert not contract.valid("WorkContextAuthoringSummary", value)


def test_budget_and_expected_identity_fail_explicitly_without_truncation_or_substitution():
    authoring_repository.bounded_size(authoring_repository.MAX_SNAPSHOT_BYTES)
    with pytest.raises(DomainError) as budget:
        authoring_repository.bounded_size(authoring_repository.MAX_SNAPSHOT_BYTES + 1)
    assert budget.value.status == 413
    with pytest.raises(DomainError) as identity:
        authoring_service._expected({"selection_digest": "a" * 64}, "b" * 64)
    assert identity.value.status == 412


def test_only_three_opt_in_gets_export_closed_independently_named_rich_types():
    actual = openapi(catalog_app())
    for path in (contract.CHOICES_PATH, contract.SNAPSHOT_PATH, contract.BUILD_PATH):
        assert set(actual["paths"][path]) == {"get"}
        assert actual["paths"][path]["get"]["security"] == [{"SessionCookie": []}]
    assert "AuthoringRichDocument" not in actual["components"]["schemas"]
    for schema in contract.SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
