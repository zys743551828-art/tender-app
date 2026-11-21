"""Synthetic exact native requirement→numeric project style→chapter tests."""
# ruff: noqa: F401,F811

import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, save, world
from authoring_package_job_fixtures import case, current, finish, input_database, launch, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import (
    adopted,
    adoption_body,
    compute,
    database,
    publish,
    request_build,
    unpublished,
)
from test_authoring_exact_revisions_pg import confirm, published
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_package_inputs_pg import add_new_parse
from test_stable_lot_identity import api, headers
from test_technical_bid_generation_journey_pg import (
    blank_target,
    build_structured_word,
    counts,
    current_layout,
    requirements,
)
from test_technical_bid_generation_journey_pg import exact as outline_only
from test_technical_saved_plan_generation_pg import authority_ref, save_plan

from apps.worker import engine
from packages.authoring import bound_format_scope
from packages.domain import storage
from packages.domain.bid_package_service import lock_bid
from packages.domain.fact_sets import evidence_basis
from packages.domain.human_decisions import append_decision
from packages.domain.runtime import ROOT, DomainError, connection, sha
from packages.rag.indexing import ensure_parse_sources

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires explicitly isolated authoring PG17")


def attach_current_authority(requirements, owner):
    bid = requirements["scope"].bid_id
    with owner.transaction():
        document = owner.execute(
            """SELECT p.id,p.document_version_id FROM design.evidence_blocks e
               JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id
               WHERE e.bid_id=%s AND e.id=%s""",
            (bid, requirements["evidence"]),
        ).fetchone()
        material = owner.execute(
            "SELECT material_id FROM design.rule_sets WHERE bid_id=%s AND id=%s",
            (bid, requirements["inventory_body"]["rule_set_id"]),
        ).fetchone()["material_id"]
        owner.execute(
            """INSERT INTO design.material_assignments
               (snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'tender',0)""",
            (material, bid, document["document_version_id"]),
        )
        owner.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s WHERE bid_id=%s", (material, bid)
        )
    with connection(True) as c:
        ensure_parse_sources(c, bid, document["id"], publish_readable=True)
    with connection() as c:
        source = UUID(requirements["evidence"])
        append_decision(
            c,
            bid,
            UUID(requirements["actor"]),
            "rule",
            UUID(requirements["rule"]),
            {
                "decision": "confirmed",
                "reason": "合成格式条款人工独立核对",
                "evidence_ids": [str(source)],
            },
            basis=evidence_basis(c, bid, [source], publish=False),
        )


def draft_path(w):
    return f"/api/v1/bids/{w['bid']}/drafts/{w['input_body']['target_section']['draft_id']}"


def apply_style(w, bindings):
    client = w["client"]
    path = draft_path(w)
    tree = client.get(path + "/structure")
    assert tree.status_code == 200, tree.text
    selected = tree.json()
    body = {
        "base_draft_revision": selected["draft_revision"],
        "style_template_version_id": selected["style_template_version_id"],
        "format_bindings": bindings,
        "format_review_ack": None,
    }
    first = client.post(
        path + "/style-template/preview", json=body, headers=headers(w, etag=tree.headers["etag"])
    )
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "requires_format_review"
    report = first.json()["format_report"]
    assert report["binding_manifest"] and report["coverage"] == "manual_field_bindings_only"
    action = client.post(
        path + "/style-template/preview",
        json=body | {"format_review_ack": report["review_digest"]},
        headers=headers(w, etag=tree.headers["etag"]),
    )
    assert action.status_code == 201, action.text
    applied = client.post(
        f"/api/v1/bids/{w['bid']}/authoring-structure-actions/{action.json()['action_id']}/resolve",
        json={"decision": "confirm"},
        headers=headers(w, etag=tree.headers["etag"]),
    )
    assert applied.status_code == 200, applied.text
    return applied.json(), report


@pytest.fixture
def confirmed_format(requirements, request):
    attach_current_authority(requirements, requirements["database"]["owner"])
    w = outline_only.__wrapped__(requirements)
    ref = authority_ref(w, requirements["evidence"])
    private = "PRIVATE-STYLE-REASON-SYNTHETIC-NOT-PROVIDER"
    fields = {
        "font_size_halfpoints": 24,
        "paragraph_after_twips": 240,
        "margin_top_twips": 1560,
        "margin_right_twips": 1680,
        "margin_bottom_twips": 1800,
        "margin_left_twips": 1920,
    }
    if getattr(request, "param", None) == "unsupported":
        fields = {"page_number": False}
    bindings = [
        {
            "rule_id": w["rule"],
            "field": field,
            "value": value,
            "source_refs": [ref],
            "reason": private,
        }
        for field, value in fields.items()
    ]
    applied, report = apply_style(w, bindings)
    assert all(report["effective_config"][field] == value for field, value in fields.items())
    w["confirmed_format"] = {
        "saved": applied,
        "report": report,
        "ref": ref,
        "private": private,
        "bindings": bindings,
        "fields": fields,
    }
    return w


def capture_body(w, *, blocker=None):
    pinned = deepcopy(w["input_body"])
    pinned["target_section"] = blank_target(
        w,
        w["confirmed_format"]["saved"],
        w["technical_journey"]["chapter"],
        expected_blockers=(blocker,) if blocker else (),
    )
    return pinned


@pytest.fixture(scope="module")
def formatted_schema(job_database):
    owner = job_database["owner"]
    with connection() as c:
        assert not bound_format_scope.installed(c)
    owner.execute((ROOT / bound_format_scope.DDL).read_text())
    with connection() as c:
        assert bound_format_scope.installed(c)
        assert not c.execute(
            "SELECT has_function_privilege('design.authoring_bound_format_assert_current(uuid)',"
            "'EXECUTE') AS granted"
        ).fetchone()["granted"]
    with connection(True) as c:
        assert bound_format_scope.installed(c)
    return job_database


@pytest.fixture
def exact(confirmed_format, formatted_schema):
    w = confirmed_format
    layout = current_layout(w, draft_path(w), w["technical_journey"]["chapter"]["section_id"])
    assert layout["snapshot_id"] == w["confirmed_format"]["saved"]["snapshot_id"]
    assert layout["state"] == "structured_layout_rechecked"
    w["input_body"] = capture_body(w)
    return w


def snapshot_row(w, snapshot_id):
    with connection() as c:
        return c.execute(
            "SELECT manifest,digest FROM design.draft_snapshots WHERE bid_id=%s AND id=%s",
            (w["bid"], snapshot_id),
        ).fetchone()


def test_frozen_numbers_and_complete_rule_reach_actual_word_but_not_provider(adopted):
    w = adopted
    bound = w["confirmed_format"]
    assert len(w["calls"]) == 1
    body = json.dumps(w["calls"][0], ensure_ascii=False)
    assert bound["private"] not in body
    for name in bound["fields"]:
        assert name not in body
    [raw] = [m["content"] for m in w["calls"][0]["messages"] if m["role"] == "user"]
    prompt = json.loads(raw)["complete_fixed_package_plan"]
    context = prompt["context"]
    assert "authoring_structure" not in context["target"]["snapshot_manifest"]
    assert "authoring_structure" not in context["target"]["snapshot"]
    assert context["method"]["bound_format_method"] == bound_format_scope.INPUT_METHOD
    assert prompt["execution_policy"]["bound_format_method"] == bound_format_scope.EXECUTION_METHOD
    assert not prompt["formal_scoring_input"]
    assert w["fixed"]["manifest"]["publication_authorized"] is False

    original = snapshot_row(w, bound["saved"]["snapshot_id"])
    now = snapshot_row(w, w["saved"]["snapshot_id"])
    assert original["digest"] != now["digest"]
    old_style = original["manifest"]["authoring_structure"]["metadata"]
    new_style = now["manifest"]["authoring_structure"]["metadata"]
    assert old_style == new_style
    assert [r["field"] for r in new_style["format_binding_manifest"]] == list(bound["fields"])

    _, word, document = build_structured_word(w)
    assert w["raw"]["replacement_text"] in document and bound["private"] not in document
    xml = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    ns = "{" + xml["w"] + "}"
    with ZipFile(BytesIO(storage.get(word["object_key"]))) as archive:
        style = ET.fromstring(archive.read("word/styles.xml"))
        body = ET.fromstring(archive.read("word/document.xml"))
    size = style.find("w:docDefaults/w:rPrDefault/w:rPr/w:sz", xml)
    spacing = style.find("w:docDefaults/w:pPrDefault/w:pPr/w:spacing", xml)
    assert size is not None and size.get(ns + "val") == "24"
    assert spacing is not None and spacing.get(ns + "after") == "240"
    margins = body.findall(".//w:pgMar", xml)
    assert margins and all(
        pg.get(ns + side) == str(bound["fields"][f"margin_{side}_twips"])
        for pg in margins
        for side in ("top", "right", "bottom", "left")
    )


def leave_current_material(w):
    ref = w["confirmed_format"]["ref"]
    with connection() as c:
        lock_bid(c, w["bid"])
        d = c.execute(
            "SELECT revision,status FROM retrieval.source_heads WHERE source_id=%s",
            (ref["source_id"],),
        ).fetchone()
        assert d == {"revision": ref["source_revision"], "status": "published"}
        c.execute(
            "UPDATE design.bid_profiles SET current_material_id=NULL WHERE bid_id=%s", (w["bid"],)
        )


def test_current_material_drift_blocks_native_authority_before_any_mock_model(queued):
    w = queued
    leave_current_material(w)
    # The Worker-native guard also runs inside reserve/dispatch, not just Python.
    with pytest.raises(psycopg.errors.CheckViolation) as denied:
        with connection(True) as c:
            c.execute("SELECT design.authoring_package_assert_job(%s)", (w["job_id"],))
    assert denied.value.diag.message_primary == "AUTHORING_PACKAGE_BOUND_FORMAT_SOURCE_CHANGED"
    finish(w)
    failed = current(w)
    assert failed["state"] == "failed"
    assert failed["error_code"] == "AUTHORING_PACKAGE_BOUND_FORMAT_SOURCE_CHANGED"
    assert not w["calls"]


def test_replaced_style_rejects_old_start_without_budget_or_model(case):
    w = case
    updated, _ = apply_style(w, [w["confirmed_format"]["bindings"][0] | {"value": 28}])
    assert updated["snapshot_id"] != w["confirmed_format"]["saved"]["snapshot_id"]
    before = counts()
    denied = launch(w)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    assert counts() == before and not w["calls"]


def test_revoked_current_layout_source_rejects_old_adoption_without_rewriting(published):
    w = published
    leave_current_material(w)
    before = counts()
    denied = confirm(w)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "AUTHORING_SOURCE_STALE"
    assert counts() == before and len(w["calls"]) == 1
    assert w["client"].get(w["action_ref"]).json()["state"] == "pending"


def check_unsupported(w, saved):
    w["confirmed_format"]["saved"] = saved
    chapter = w["technical_journey"]["chapter"]
    observed = current_layout(w, draft_path(w), chapter["section_id"])
    assert observed["snapshot_id"] == saved["snapshot_id"]
    assert observed["state"] == "structure_not_supported"
    assert "bound_project_format" in observed["unsupported_reasons"]
    pinned = capture_body(w, blocker="AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED")
    before = counts()
    result = save(w, body=pinned)
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED"
    assert counts() == before


@pytest.mark.parametrize("confirmed_format", ["unsupported"], indirect=True)
def test_registration_of_other_layout_fields_does_not_broaden_generation(
    confirmed_format, formatted_schema
):
    w = confirmed_format
    check_unsupported(w, w["confirmed_format"]["saved"])
    native = snapshot_row(w, w["confirmed_format"]["saved"]["snapshot_id"])
    assert (
        native["manifest"]["authoring_structure"]["metadata"]["effective_style"]["page_number"]
        is False
    )


def test_saved_plan_and_binding_remain_untouched_and_out_of_this_scope(
    confirmed_format, formatted_schema
):
    w = confirmed_format
    saved = save_plan(
        w,
        w["technical_journey"]["chapter"],
        goal="合成计划不随版式预览或拒绝更改",
        ref=w["confirmed_format"]["ref"],
    )
    selected = snapshot_row(w, saved["snapshot_id"])
    structure = selected["manifest"]["authoring_structure"]
    assert len(structure["plans"]) == 1 and len(structure["metadata"]["format_bindings"]) == 6
    check_unsupported(w, dict(saved, snapshot_digest=selected["digest"]))
    assert snapshot_row(w, saved["snapshot_id"]) == selected


def test_reparsed_authority_is_not_silently_used_for_frozen_binding(queued):
    w = queued
    ref = w["confirmed_format"]["ref"]
    with connection() as c:
        old = c.execute(
            "SELECT parse_id FROM design.evidence_blocks WHERE bid_id=%s AND id=%s",
            (w["bid"], ref["evidence_id"]),
        ).fetchone()["parse_id"]
    exact_authority = SimpleNamespace(parse=SimpleNamespace(parse_run_id=old))
    assert add_new_parse(w | {"member": exact_authority}) != old
    layout = current_layout(w, draft_path(w), w["technical_journey"]["chapter"]["section_id"])
    assert layout["state"] == "layout_basis_changed"
    finish(w)
    failed = current(w)
    assert failed["state"] == "failed"
    assert failed["error_code"] == "AUTHORING_PACKAGE_BOUND_FORMAT_SOURCE_CHANGED"
    assert not w["calls"]


def test_word_publish_rechecks_authority_but_retains_prior_advisory(adopted):
    w = adopted
    ready, old_word, _ = build_structured_word(w)
    prior_document = adoption_body(w, ready)["member"]["document_version_id"]
    structure = w["client"].get(draft_path(w) + "/structure").json()
    new = {
        "draft_id": w["input_body"]["target_section"]["draft_id"],
        "draft_revision": w["saved"]["draft_revision"],
        "follow_up": "none",
        "formats": ["docx"],
        "directory_template_version_id": structure["directory_template_version_id"],
        "style_template_version_id": structure["style_template_version_id"],
        "pagination_mode": "chapter_start_new_page",
    }
    accepted = request_build(w, body=new)
    assert accepted.status_code == 202, accepted.text
    build_id = accepted.json()["resource_id"]
    assert ready["id"] != build_id
    with connection() as c:
        message = c.execute(
            "SELECT o.payload FROM design.builds b JOIN design.outbox o ON o.operation_id=b.operation_id "
            "WHERE b.id=%s AND o.topic='tender.task.export.v1'",
            (build_id,),
        ).fetchone()["payload"]
    lease = engine.acquire(message)
    assert lease is not None
    build = {"id": build_id, "message": message, "lease": lease}
    bytes_observed = compute(build)
    leave_current_material(w)
    future = request_build(w, body=new)
    assert future.status_code == 409, future.text
    assert future.json()["code"] == "AUTHORING_SOURCE_STALE"
    with pytest.raises(DomainError) as denied:
        publish(build, bytes_observed)
    assert denied.value.code == "AUTHORING_SOURCE_STALE"
    unpublished(build)
    historic = w["client"].post(
        f"/api/v1/bids/{w['bid']}/builds/{ready['id']}/technical-docx-check",
        json={"document_version_id": prior_document, "filename": "Synthetic technical.docx"},
        headers=headers(w),
    )
    assert historic.status_code == 200, historic.text
    data = historic.json()
    assert data["artifact_sha256"] == old_word["digest"]
    assert data["historical_advisory"] and not data["publication_authorized"]
    assert len(w["calls"]) == 1
