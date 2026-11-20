"""Real saved plan + six project format fields, synthetic data and offline model."""
# ruff: noqa: F401,F811

import json
from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from authoring_package_input_fixtures import ADMIN_DSN, world
from authoring_package_job_fixtures import case, current, finish, input_database, launch, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import adopted, database
from test_authoring_exact_revisions_pg import confirm, published
from test_authoring_exact_revisions_pg import database as revision_database
from test_stable_lot_identity import api, headers
from test_technical_bid_generation_journey_pg import (
    build_structured_word,
    counts,
    current_layout,
    requirements,
)
from test_technical_bound_format_generation_pg import (
    apply_style,
    capture_body,
    confirmed_format,
    draft_path,
    formatted_schema,
    leave_current_material,
    snapshot_row,
)
from test_technical_saved_plan_generation_pg import PRIVATE_NOT_FACT, planned_schema, save_plan

from packages.authoring import bound_format_scope, combined_authoring_scope, saved_chapter_plans
from packages.domain import storage
from packages.domain.runtime import ROOT, connection

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated synthetic PostgreSQL17")
PLAN_GOAL = "PRIVATE-RETAINED-SYNTHETIC-DRAFT-PLAN-GOAL"


@pytest.fixture(scope="module")
def combined_schema(planned_schema, formatted_schema):
    with connection() as c:
        assert saved_chapter_plans.installed(c) and bound_format_scope.installed(c)
        assert not combined_authoring_scope.installed(c)
    formatted_schema["owner"].execute((ROOT / combined_authoring_scope.DDL).read_text())
    for worker in (False, True):
        with connection(worker) as c:
            assert combined_authoring_scope.installed(c)
            assert not c.execute(
                "SELECT has_function_privilege('design.authoring_combined_scope_installed()', 'EXECUTE') AS granted"
            ).fetchone()["granted"]
    return formatted_schema


def save_without_reference(w, chapter):
    client = w["client"]
    path = draft_path(w)
    base = client.get(path)
    assert base.status_code == 200, base.text
    written = client.put(
        f"{path}/sections/{chapter['section_id']}/plan",
        json={
            "base_draft_revision": base.json()["revision"],
            "base_plan_revision": 0,
            "state": "drafting",
            "goal": PLAN_GOAL,
            "key_points": [],
            "pending_facts": [PRIVATE_NOT_FACT],
            "rule_ids": [],
            "source_refs": [],
            "planned_pages": 3,
            "budget_basis": "manual",
            "budget_rule_id": None,
            "budget_note": "internal manual plan note",
        },
        headers=headers(w, etag=base.headers["etag"]),
    )
    assert written.status_code == 200, written.text
    return written.json()


@pytest.fixture
def combined_draft(confirmed_format, request):
    w = confirmed_format
    chapter = w["technical_journey"]["chapter"]
    if getattr(request, "param", None) == "plan_without_source":
        written = save_without_reference(w, chapter)
    else:
        written = save_plan(w, chapter, goal=PLAN_GOAL, ref=w["confirmed_format"]["ref"])
    before = snapshot_row(w, written["snapshot_id"])
    w["confirmed_format"]["saved"] = dict(written, snapshot_digest=before["digest"])
    ext = before["manifest"]["authoring_structure"]
    assert ext["plans"][written["plan"]["id"]] == written["plan"]
    assert len(ext["metadata"]["format_bindings"]) == 6
    w["retained"] = {
        "plan": written["plan"],
        "structure": ext,
        "snapshot_id": written["snapshot_id"],
    }
    return w


@pytest.fixture
def exact(combined_draft, combined_schema):
    w = combined_draft
    assert (
        current_layout(w, draft_path(w), w["technical_journey"]["chapter"]["section_id"])["state"]
        == "structured_layout_rechecked"
    )
    w["input_body"] = capture_body(w)
    return w


def test_independently_frozen_plan_and_layout_are_kept_through_editable_word(adopted):
    w = adopted
    assert len(w["calls"]) == 1
    call = w["calls"][0]
    text = json.dumps(call, ensure_ascii=False)
    for private in (
        PLAN_GOAL,
        PRIVATE_NOT_FACT,
        w["confirmed_format"]["private"],
        "chapter_start_new_page",
        "effective_style",
        "format_binding_manifest",
        *w["confirmed_format"]["fields"],
    ):
        assert private not in text
    [message] = [msg["content"] for msg in call["messages"] if msg["role"] == "user"]
    projected = json.loads(message)["complete_fixed_package_plan"]
    context = projected["context"]
    assert "authoring_structure" not in context["target"]["snapshot_manifest"]
    assert "authoring_structure" not in context["target"]["snapshot"]
    assert context["method"]["combined_scope_method"] == combined_authoring_scope.INPUT_METHOD
    assert (
        projected["execution_policy"]["combined_scope_method"]
        == combined_authoring_scope.EXECUTION_METHOD
    )
    assert projected["saved_chapter_plan_links"] == {
        "requirement_ids": [w["rule"]],
        "authority_evidence_ids": [w["confirmed_format"]["ref"]["evidence_id"]],
    }

    new = snapshot_row(w, w["saved"]["snapshot_id"])["manifest"]["authoring_structure"]
    assert new["plans"] == w["retained"]["structure"]["plans"]
    assert new["metadata"] == w["retained"]["structure"]["metadata"]
    layout = current_layout(w, draft_path(w), w["technical_journey"]["chapter"]["section_id"])
    assert layout["plan_state"] == "target_stale"
    assert layout["unsupported_reasons"] == ["saved_chapter_plans"]
    _, word, rendered = build_structured_word(w, gate_state="structure_not_supported")
    assert w["raw"]["replacement_text"] in rendered and PLAN_GOAL not in rendered
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with ZipFile(BytesIO(storage.get(word["object_key"]))) as archive:
        styles = ET.fromstring(archive.read("word/styles.xml"))
        content = ET.fromstring(archive.read("word/document.xml"))
    assert any(e.attrib.get(ns + "val") == "24" for e in styles.iter(ns + "sz"))
    assert any(e.attrib.get(ns + "after") == "240" for e in styles.iter(ns + "spacing"))
    margins = list(content.iter(ns + "pgMar"))
    assert margins and all(
        element.attrib[ns + side] == str(w["confirmed_format"]["fields"][f"margin_{side}_twips"])
        for element in margins
        for side in ("top", "right", "bottom", "left")
    )
    assert not w["fixed"]["manifest"]["publication_authorized"]


def advance(w, changed):
    original = w["retained"]
    if changed == "plan":
        advanced = save_plan(
            w,
            w["technical_journey"]["chapter"],
            goal="合成版式不重置",
            ref=w["confirmed_format"]["ref"],
            base_plan_revision=original["plan"]["revision"],
        )
        assert advanced["plan"]["revision"] == original["plan"]["revision"] + 1
    else:
        advanced, _ = apply_style(w, [w["confirmed_format"]["bindings"][0] | {"value": 28}])
    assert advanced["snapshot_id"] != original["snapshot_id"]
    assert (
        original["structure"]
        == snapshot_row(w, original["snapshot_id"])["manifest"]["authoring_structure"]
    )


@pytest.mark.parametrize("changed", ["plan", "layout"])
def test_editing_either_dimension_cannot_start_on_the_old_combined_input(case, changed):
    w = case
    advance(w, changed)
    before = counts()
    rejected = launch(w)
    assert (
        rejected.status_code == 409 and rejected.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    ), rejected.text
    assert counts() == before and not w["calls"]


@pytest.mark.parametrize("changed", ["plan", "layout"])
def test_editing_either_dimension_cannot_adopt_a_published_combined_candidate(published, changed):
    w = published
    advance(w, changed)
    before = counts()
    rejected = confirm(w)
    assert (
        rejected.status_code == 409 and rejected.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    ), rejected.text
    assert w["client"].get(w["action_ref"]).json()["state"] == "pending"
    assert counts() == before and len(w["calls"]) == 1


@pytest.mark.parametrize(
    ("combined_draft", "expected"),
    [
        ("plan_without_source", "AUTHORING_PACKAGE_BOUND_FORMAT_SOURCE_CHANGED"),
        ("plan_with_source", "AUTHORING_PACKAGE_SAVED_PLAN_SOURCE_CHANGED"),
    ],
    indirect=["combined_draft"],
)
def test_native_worker_enforces_both_source_validators_before_provider(queued, expected):
    w = queued
    leave_current_material(w)
    finish(w)
    stopped = current(w)
    assert stopped["state"] == "failed"
    assert stopped["error_code"] == expected
    assert not w["calls"]
