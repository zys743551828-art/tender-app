"""Explicit package task scope, stable legacy bytes and fail-closed native boundaries."""
# ruff: noqa: F401,F811

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from test_package_scope_review import case as scope_case
from test_package_scope_review import uid

from apps.api.export_openapi import implemented_openapi
from apps.api.task_routes import router
from packages.domain import bid_package_review_runs as native_runs
from packages.domain import bid_package_scope_review as admission
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError
from packages.tasks import inputs, package_inputs, package_runs
from packages.tasks.draft_interpreter import TaskDraftRequest, interpret
from packages.tasks.models import TemplateRequest


@pytest.fixture
def package_case(scope_case):
    manifest = scope_case["manifest"]
    value = {
        **{key: manifest["scope"][key] for key in package_inputs.SCOPE_KEYS[1:]},
        "frozen_input_id": manifest["frozen_input"]["id"],
        "frozen_input_digest": manifest["frozen_input"]["digest"],
        "execution_input_id": manifest["execution_input"]["id"],
        "execution_input_digest": manifest["execution_input"]["digest"],
        "dependency_plan_id": manifest["dependency_plan"]["id"],
        "dependency_plan_digest": manifest["dependency_plan"]["digest"],
        "method_digest": manifest["executor_method"]["digest"],
    }
    template = TemplateRequest(
        name="合成整包否决核对",
        task_kind="denial_check",
        instructions="核对所选原包中的已声明要求；结果供人工查看",
        source_selection={"mode": "exact_package_review", "input": value},
    )
    return scope_case | {"selected": value, "template": template}


def test_explicit_selection_keeps_full_exact_scope_and_no_body_fallback(package_case):
    case = package_case
    config = case["template"].model_dump(mode="json")
    selected = package_inputs.selection(config)
    assert selected == case["selected"]
    context = package_inputs.context(case["scope"][0], selected, case["manifest"])
    assert context["subject"] == {"kind": "bid_package", **case["manifest"]["scope"]}
    assert context["review_input_digest"] == digest(case["manifest"])
    assert context["selection"] == selected and context["overall_coverage"] == "partial"
    assert not context["formal_scoring_eligible"] and not context["submission_eligible"]
    assert "body_version_id" not in context
    selected["package_id"] = uid(900)
    assert context["selection"] == case["selected"]


@pytest.mark.parametrize(
    "field",
    package_inputs.SCOPE_KEYS[1:]
    + (
        "frozen_input_id",
        "frozen_input_digest",
        "execution_input_id",
        "execution_input_digest",
        "dependency_plan_id",
        "dependency_plan_digest",
        "method_digest",
    ),
)
def test_any_explicit_reference_mismatch_rejects_whole_context(package_case, field):
    selected = deepcopy(package_case["selected"])
    selected[field] = "0" * 64 if field.endswith("digest") else uid(900)
    with pytest.raises(DomainError) as error:
        package_inputs.context(package_case["scope"][0], selected, package_case["manifest"])
    assert error.value.code == "TASK_PACKAGE_BINDING_INVALID"


def test_fee_safety_ignores_template_navigation_and_rerun_identity(package_case):
    case = package_case
    context = package_inputs.context(case["scope"][0], case["selected"], case["manifest"])
    changed = deepcopy(context)
    changed["selection"]["execution_input_id"] = uid(901)
    changed["selection"]["dependency_plan_id"] = uid(902)
    changed["review_input_digest"] = "0" * 64
    assert package_inputs.fee_scope(changed) == package_inputs.fee_scope(context)
    assert package_inputs.input_digest(uid(100), "1" * 64, context) != package_inputs.input_digest(
        uid(101), "1" * 64, context
    )
    assert package_inputs.input_digest(uid(100), "1" * 64, context) != package_inputs.input_digest(
        uid(100), "1" * 64, changed
    )
    changed["model_input_digest"] = "2" * 64
    assert package_inputs.fee_scope(changed) != package_inputs.fee_scope(context)


@pytest.mark.parametrize(
    "kind,trigger,section",
    [
        ("scoring_review", {"mode": "manual"}, None),
        ("supplement_impact", {"mode": "manual"}, None),
        ("chapter_suggestion", {"mode": "manual"}, uid(120)),
        ("denial_check", {"mode": "schedule", "cron": "0 9 * * *"}, None),
        ("denial_check", {"mode": "material_updated"}, None),
    ],
)
def test_exact_package_mode_cannot_be_misrepresented_as_other_action_or_trigger(
    package_case, kind, trigger, section
):
    data = package_case["template"].model_dump(mode="json")
    data.update(task_kind=kind, trigger=trigger, section_id=section)
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(data)


def test_legacy_source_bytes_and_unselected_draft_stay_unchanged():
    template = TemplateRequest(name="旧任务", task_kind="denial_check", instructions="核对否决项")
    assert template.model_dump(mode="json")["source_selection"] == {
        "mode": "current_project",
        "version_ids": [],
    }
    draft = interpret(TaskDraftRequest(request="核对否决项"))
    assert draft.model_dump(mode="json")["source_selection"] == {
        "mode": "current_project",
        "version_ids": [],
    }
    assert draft.target_description == "本项目当前正文与所选来源"


@pytest.mark.parametrize("mode", ["material_updated", "schedule"])
def test_explicit_trigger_mode_preserves_the_same_exact_selection(package_case, mode):
    data = package_case["template"].model_dump(mode="json")
    data["source_selection"]["mode"] = "exact_package_trigger"
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(data)
    data["trigger"] = {"mode": mode, **({"cron": "0 9 * * *"} if mode == "schedule" else {})}
    accepted = TemplateRequest.model_validate(data).model_dump(mode="json")
    assert package_inputs.selection(accepted) == package_case["selected"]
    assert accepted["source_selection"]["mode"] == "exact_package_trigger"
    accepted["trigger"]["mode"] = "unknown"
    with pytest.raises(DomainError):
        package_inputs.selection(accepted)


@pytest.mark.parametrize("source", [{}, {"version_ids": []}])
def test_legacy_source_with_omitted_mode_keeps_identical_canonical_request(source):
    base = {"name": "旧任务", "task_kind": "denial_check", "instructions": "核对否决项"}
    assert TemplateRequest.model_validate(base | {"source_selection": source}).model_dump(
        mode="json"
    ) == TemplateRequest.model_validate(base).model_dump(mode="json")
    request = TaskDraftRequest(request="核对否决项", source_selection=source)
    assert request.model_dump(mode="json") == TaskDraftRequest(request="核对否决项").model_dump(
        mode="json"
    )


@pytest.mark.parametrize("source", [{"version_ids": [uid(20)]}, {"input": {"package_id": uid(20)}}])
def test_omitted_mode_never_erases_invalid_legacy_versions_or_infers_exact_scope(source):
    with pytest.raises(ValidationError):
        TemplateRequest(
            name="显式来源",
            task_kind="denial_check",
            instructions="核对否决项",
            source_selection=source,
        )
    with pytest.raises(ValidationError):
        TaskDraftRequest(request="核对否决项", source_selection=source)


@pytest.mark.parametrize(
    "text,ready",
    [
        ("核对附件的否决项", True),
        ("每天9点核对附件的否决项", False),
        ("资料更新后核对附件的否决项", False),
        ("复核附件评分", False),
        ("核对否决并自动确认所有规则", False),
    ],
)
def test_bounded_interpreter_preserves_explicit_package_and_prohibited_actions(
    package_case, text, ready
):
    draft = interpret(
        TaskDraftRequest(request=text, source_selection=package_case["template"].source_selection)
    )
    assert draft.ready_for_template_form is ready
    assert draft.source_selection == package_case["template"].source_selection
    assert draft.target_description == "所选精确投标包、冻结输入、执行准备与依赖计划"
    assert draft.template_saved is draft.run_created is draft.formal_decisions_allowed is False


def test_metadata_selection_reads_only_exact_saved_records(package_case, monkeypatch):
    case = package_case
    calls = []
    for module, name, value in (
        (package_inputs.frozen_inputs, "load_input", case["frozen"]),
        (package_inputs.prepared_inputs, "load_packet", case["prepared"]),
        (package_inputs.plans, "load", case["plan"]),
    ):

        def read(c, *args, saved=value, label=name):
            calls.append((label, args))
            return saved

        monkeypatch.setattr(module, name, read)
    monkeypatch.setattr(
        admission, "observe", lambda *a: pytest.fail("Saving must not admit originals")
    )
    monkeypatch.setattr(
        admission, "verify", lambda *a: pytest.fail("Saving must not read original bytes")
    )
    assert package_inputs.selected(None, case["scope"][0], case["selected"]) == case["selected"]
    assert all(args[0] == case["scope"] for _, args in calls)
    stale = case["selected"] | {"execution_input_digest": "0" * 64}
    with pytest.raises(DomainError, match="所选整包输入摘要"):
        package_inputs.selected(None, case["scope"][0], stale)


def test_old_capture_cannot_fall_back_to_current_body_for_exact_package(package_case):
    with pytest.raises(DomainError) as error:
        inputs.capture(
            None, package_case["scope"][0], package_case["template"].model_dump(mode="json")
        )
    assert error.value.code == "TASK_PACKAGE_EXPLICIT_COORDINATOR_REQUIRED"


@pytest.mark.parametrize(
    "body,code",
    [
        ({"rerun": True}, "TASK_PACKAGE_REPREPARE_REQUIRED"),
        ({"rerun": 1}, "TASK_PACKAGE_REQUEST_INVALID"),
        ({"rerun": False, "native_run_id": uid(3)}, "TASK_PACKAGE_REQUEST_INVALID"),
    ],
)
def test_package_run_never_invents_a_rerun_or_accepts_hidden_scope(body, code):
    with pytest.raises(DomainError) as error:
        package_runs._assert_request(body)
    assert error.value.code == code


@pytest.mark.parametrize("change", ["type", "scope", "frozen", "prepared", "request", "worker"])
def test_locked_native_publication_requires_same_privately_verified_request(package_case, change):
    case = package_case
    selected = case["selected"]
    body = package_inputs.request(selected)
    observed = SimpleNamespace(
        scope=case["scope"],
        frozen_id=selected["frozen_input_id"],
        prepared_id=selected["execution_input_id"],
        _request_text=canonical(body).decode(),
        worker=False,
    )
    if change == "scope":
        observed.scope = (uid(901), *case["scope"][1:])
    elif change == "frozen":
        observed.frozen_id = uid(901)
    elif change == "prepared":
        observed.prepared_id = uid(901)
    elif change == "request":
        observed._request_text = canonical(body | {"dependency_plan_digest": "0" * 64}).decode()
    elif change == "worker":
        observed.worker = True
    verified = observed if change == "type" else admission.VerifiedScopeReview(observed)
    with pytest.raises(TypeError if change == "type" else DomainError):
        native_runs.start_verified(
            None,
            uid(20),
            case["scope"],
            selected["frozen_input_id"],
            selected["execution_input_id"],
            "explicit-key",
            body,
            verified,
        )


def test_actual_task_contract_exposes_union_and_truthful_manual_capability():
    app = FastAPI()
    app.include_router(router)
    schemas = implemented_openapi(app)["components"]["schemas"]
    source = schemas["TemplateRequest"]["properties"]["source_selection"]
    assert set(source["discriminator"]["mapping"]) == {
        "current_project",
        "selected_versions",
        "exact_package_review",
        "exact_package_trigger",
        "exact_package_authoring",
    }
    assert schemas["SourceSelection"]["properties"].keys() == {"mode", "version_ids"}
    assert len(schemas["PackageReviewSelection"]["required"]) == 10
    capability = schemas["PackageTaskManualCapabilities"]["properties"]
    assert capability["trigger"]["const"] == "manual"
    assert capability["overall_coverage"]["const"] == "partial"
    assert capability["submission_eligible"]["const"] is False
    assert capability["automatic_input_selection"]["const"] is False
    authoring = schemas["PackageTaskAuthoringCapabilities"]["properties"]
    assert authoring["trigger"]["const"] == "manual"
    assert authoring["source_scope"]["const"] == "exact_package_context"
    assert authoring["rerun_supported"]["const"] is False
    assert authoring["apply_available"]["const"] is False
    assert authoring["build_available"]["const"] is False
