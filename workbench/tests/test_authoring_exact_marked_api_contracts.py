"""Additive B7 API selection does not broaden the frozen B5/B6 contracts."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from packages.authoring import exact_marked_text_edits, exact_text_edit_service, exact_text_edits
from packages.authoring.exact_marked_text_edit_contracts import (
    AuthoringExactMarkedTextEditCapabilities,
    AuthoringExactMarkedTextEditRequest,
    AuthoringExactMarkedTextEditResult,
)
from packages.authoring.exact_text_edit_contracts import (
    AuthoringExactMultiTextEditRequest,
    AuthoringExactMultiTextEditResult,
    AuthoringExactTextEditRequest,
    AuthoringExactTextEditResult,
)


def single():
    return {
        "base_draft_revision": 2,
        "section_revision_id": str(uuid4()),
        "node_id": "synthetic-stable-node",
        "before_node_digest": "a" * 64,
        "replacement_text": "Explicit human wording",
        "reason": "Synthetic scope validation",
    }


def test_new_capability_is_separate_and_fail_closed(monkeypatch):
    monkeypatch.setattr(exact_text_edits, "available", lambda _c: True)
    monkeypatch.setattr(exact_text_edits, "multi_installed", lambda _c: True)
    monkeypatch.setattr(exact_marked_text_edits, "available", lambda _c: False)
    old = exact_text_edit_service.capabilities(None)
    new = exact_text_edit_service.marked_capabilities(None)
    assert old["protocol"] == "authoring-exact-text-edit-capabilities/2"
    assert old["supported_content"] == "plain_text_stable_nodes"
    assert "preserves_marks" not in old
    assert AuthoringExactMarkedTextEditCapabilities.model_validate(new).available is False
    assert new["blocking_reasons"] == ["AUTHORING_EXACT_MARKED_TEXT_EDIT_NOT_CONFIGURED"]
    monkeypatch.setattr(exact_marked_text_edits, "available", lambda _c: True)
    ready = exact_text_edit_service.marked_capabilities(None)
    assert ready["available"] is True
    assert ready["blocking_reasons"] == []
    assert ready["preserves_marks"] is True
    assert exact_text_edit_service.capabilities(None) == old


def test_request_and_result_dispatch_remain_explicit():
    one = single()
    marked = {**one, "protocol": "authoring-exact-marked-text-edit/1"}
    batch = {
        **{key: one[key] for key in ("base_draft_revision", "section_revision_id", "reason")},
        "protocol": "authoring-exact-multi-text-edit/1",
        "edits": [
            {key: one[key] for key in ("node_id", "before_node_digest", "replacement_text")},
            {
                "node_id": "other-stable-node",
                "before_node_digest": "b" * 64,
                "replacement_text": "Other human wording",
            },
        ],
    }
    adapter = TypeAdapter(
        AuthoringExactTextEditRequest
        | AuthoringExactMultiTextEditRequest
        | AuthoringExactMarkedTextEditRequest
    )
    assert isinstance(adapter.validate_python(one), AuthoringExactTextEditRequest)
    assert isinstance(adapter.validate_python(batch), AuthoringExactMultiTextEditRequest)
    assert isinstance(adapter.validate_python(marked), AuthoringExactMarkedTextEditRequest)
    assert exact_text_edit_service.module_for(one) is exact_text_edits
    assert exact_text_edit_service.module_for(batch) is exact_text_edits
    assert exact_text_edit_service.module_for(marked) is exact_marked_text_edits
    assert exact_text_edit_service.result_model(one) is AuthoringExactTextEditResult
    assert exact_text_edit_service.result_model(batch) is AuthoringExactMultiTextEditResult
    assert exact_text_edit_service.result_model(marked) is AuthoringExactMarkedTextEditResult
    with pytest.raises(ValidationError):
        AuthoringExactTextEditRequest.model_validate(marked)
    with pytest.raises(ValidationError):
        AuthoringExactMarkedTextEditRequest.model_validate(one)


@pytest.mark.parametrize("field", ["marks", "source_refs", "rule_ids", "qualification", "origin"])
def test_api_marked_request_cannot_carry_source_or_style_authority(field):
    value = {**single(), "protocol": "authoring-exact-marked-text-edit/1", field: []}
    with pytest.raises(ValidationError):
        AuthoringExactMarkedTextEditRequest.model_validate(value)


def test_unknown_marked_protocol_cannot_fall_back_to_plain():
    value = {**single(), "protocol": "authoring-exact-marked-text-edit/unknown"}
    before = deepcopy(value)
    with pytest.raises(ValidationError):
        exact_text_edit_service.module_for(value).parse_request(value)
    assert value == before
