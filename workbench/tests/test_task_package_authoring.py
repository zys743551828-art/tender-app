"""Exact authoring task contracts and private draft intent, without execution."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.tasks.draft_interpreter import TaskDraftRequest, interpret
from packages.tasks.models import TemplateRequest


def configuration():
    return {
        "name": "明确整包编写",
        "task_kind": "chapter_suggestion",
        "instructions": "核对所选完整整包并提出章节建议",
        "section_id": str(uuid4()),
        "source_selection": {
            "mode": "exact_package_authoring",
            "input": {"authoring_input_id": str(uuid4()), "authoring_input_digest": "a" * 64},
        },
    }


@pytest.mark.parametrize("mode", ["material_updated", "schedule"])
def test_exact_authoring_template_rejects_automatic_triggers(mode):
    body = configuration()
    body["trigger"] = {"mode": mode, **({"cron": "0 8 * * *"} if mode == "schedule" else {})}
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(body)


@pytest.mark.parametrize("kind", ["denial_check", "scoring_review", "supplement_impact"])
def test_fixed_authoring_input_cannot_be_another_task(kind):
    body = configuration() | {"task_kind": kind, "section_id": None}
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(body)


def test_exact_draft_keeps_selected_input_and_explicit_section_without_authorization():
    body = configuration()
    value = interpret(
        TaskDraftRequest(
            request="用指定来源编写章节建议",
            section_id=body["section_id"],
            source_selection=body["source_selection"],
        )
    )
    assert value.ready_for_template_form
    assert str(value.section_id) == body["section_id"]
    assert value.source_selection.model_dump(mode="json") == body["source_selection"]
    assert value.trigger.mode == "manual"
    assert not value.template_saved and not value.run_created and not value.formal_decisions_allowed


@pytest.mark.parametrize(
    "text", ["每天8点用整包编写章节建议", "资料更新后用整包编写章节建议", "用整包核对否决项"]
)
def test_unsupported_private_intent_stays_unresolved(text):
    body = configuration()
    value = interpret(
        TaskDraftRequest(
            request=text, section_id=body["section_id"], source_selection=body["source_selection"]
        )
    )
    assert not value.ready_for_template_form
    assert value.unresolved
    assert value.source_selection.model_dump(mode="json") == body["source_selection"]
    assert not value.run_created


def test_exact_selection_refuses_missing_digest_and_legacy_fields():
    body = configuration()
    del body["source_selection"]["input"]["authoring_input_digest"]
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(body)
    body = configuration()
    body["source_selection"]["version_ids"] = [str(uuid4())]
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(body)
