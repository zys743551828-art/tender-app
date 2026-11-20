"""One actual outline-to-Word path: native DB/Worker, synthetic inputs and model."""
# ruff: noqa: F401,F811

from copy import deepcopy
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from authoring_package_input_fixtures import ADMIN_DSN, save, world
from authoring_package_input_fixtures import exact as base_exact
from authoring_package_job_fixtures import bind_task, case, finish, input_database, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import (
    adopted,
    adoption_body,
    compute,
    database,
    publish,
    request_build,
)
from test_authoring_exact_revisions_pg import confirm, published, qualified
from test_authoring_exact_revisions_pg import database as revision_database
from test_bid_package_requirements_api import prepare_requirements
from test_stable_lot_identity import api, headers

from apps.worker import engine
from packages.authoring import package_outputs
from packages.contracts.authoring_input_catalog_api import NODES_PATH
from packages.domain import storage
from packages.domain.runtime import connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires explicitly isolated authoring PG17")


@pytest.fixture
def requirements(world):
    return prepare_requirements(world, statement="合成要求：明确施工进度与工期，说明质量验收。")


def current_layout(w, draft_path, section_id):
    def counts():
        with connection() as c:
            return c.execute(
                """SELECT (SELECT count(*) FROM design.commands) AS commands,
                (SELECT count(*) FROM design.audit_entries) AS audits,
                (SELECT count(*) FROM design.operations) AS operations,
                (SELECT count(*) FROM design.model_calls) AS calls"""
            ).fetchone()

    before = counts()
    found = w["client"].get(f"{draft_path}/sections/{section_id}/technical-authoring-layout")
    assert found.status_code == 200, found.text
    assert counts() == before
    result = found.json()
    assert result["bid_id"] == w["bid"] and result["section_id"] == section_id
    return result


@pytest.fixture
def exact(requirements):
    w = base_exact.__wrapped__(requirements)
    client = w["client"]
    body = w["input_body"]
    source = body["package_context"]
    target = body["target_section"]
    base = f"/api/v1/bids/{w['bid']}"
    draft_path = base + "/drafts/" + target["draft_id"]
    current = client.get(draft_path)
    assert current.status_code == 200, current.text
    etag = current.headers["etag"]
    assert current_layout(w, draft_path, target["section_id"])["state"] == "plain_draft"
    context = {
        role: {
            "package_id": source[role]["package_id"],
            "revision_id": source[role]["revision_id"],
            "digest": source[role]["manifest_digest"],
        }
        for role in ("target", "authority")
    }
    preview = client.post(
        draft_path + "/technical-outline/preview",
        json={
            "base_draft_revision": target["base_draft_revision"],
            "basis": {
                **context,
                "inventory": {key: source["inventory"][key] for key in ("id", "digest")},
            },
            "chapter_keys": ["schedule", "quality"],
        },
        headers=headers(w, etag=etag),
    )
    assert preview.status_code == 201, preview.text
    proposal = preview.json()
    chapter_ids = {key.rsplit("-", 1)[-1]: value for key, value in proposal["created_ids"].items()}
    assert set(chapter_ids) == {"schedule", "quality"}
    assert client.get(draft_path).headers["etag"] == etag
    confirmation = client.post(
        f"{base}/authoring-structure-actions/{proposal['action_id']}/resolve",
        json={"decision": "confirm"},
        headers=headers(w, etag=etag),
    )
    assert confirmation.status_code == 200, confirmation.text
    outline = confirmation.json()
    guard = current_layout(w, draft_path, chapter_ids["schedule"])
    assert guard["state"] == "layout_review_required"
    assert guard["snapshot_id"] == outline["snapshot_id"]
    assert not guard["ordinary_structure_protected"]

    # Layout review is a separate explicit operation before exact authoring.
    # No additional format field is inferred or treated as compliant.
    outlined_document = client.get(draft_path)
    assert outlined_document.status_code == 200, outlined_document.text
    style = client.get(draft_path + "/structure").json()
    assert style["snapshot_id"] == outline["snapshot_id"]
    style_path = draft_path + "/style-template/preview"
    style_condition = outlined_document.headers["etag"]
    style_body = {
        "base_draft_revision": outline["draft_revision"],
        "style_template_version_id": style["style_template_version_id"],
        "format_bindings": [],
        "format_review_ack": None,
    }
    layout_review = client.post(
        style_path, json=style_body, headers=headers(w, etag=style_condition)
    )
    assert layout_review.status_code == 200, layout_review.text
    report = layout_review.json()
    assert report["state"] == "requires_format_review" and report["action_id"] is None
    assert w["rule"] in report["format_report"]["unjudged_rule_ids"]
    layout_preview = client.post(
        style_path,
        json={**style_body, "format_review_ack": report["format_report"]["review_digest"]},
        headers=headers(w, etag=style_condition),
    )
    assert layout_preview.status_code == 201, layout_preview.text
    layout_confirm = client.post(
        f"{base}/authoring-structure-actions/{layout_preview.json()['action_id']}/resolve",
        json={"decision": "confirm"},
        headers=headers(w, etag=style_condition),
    )
    assert layout_confirm.status_code == 200, layout_confirm.text
    applied = layout_confirm.json()
    assert applied["draft_revision"] == outline["draft_revision"] + 1
    current_gate = current_layout(w, draft_path, chapter_ids["schedule"])
    assert current_gate["state"] == "structured_layout_rechecked"
    assert current_gate["snapshot_id"] == applied["snapshot_id"]
    assert not current_gate["ordinary_structure_protected"]

    frozen = client.get(f"{base}/work-contexts/draft_snapshot/{applied['snapshot_id']}")
    assert frozen.status_code == 200, frozen.text
    snapshot = frozen.json()
    assert snapshot["current_observation"]["draft_head"]["status"] == "matched"
    assert snapshot["selection"]["snapshot_digest"] == applied["snapshot_digest"]
    sections = {item["section_id"]: item for item in snapshot["document"]["sections"]}
    chapter = sections[chapter_ids["schedule"]]
    quality = sections[chapter_ids["quality"]]
    assert chapter["title"] == "施工进度与资源配置"
    assert quality["title"] == "质量管理与验收"
    assert quality["content"] == proposal["after_sections"][quality["section_id"]]

    body["target_section"] = blank_target(w, applied, chapter)
    w["technical_journey"] = {"chapter": chapter, "quality": quality, "snapshot": applied}
    return w


def blank_target(w, applied, chapter, *, current=True):
    client = w["client"]
    selected = client.get(
        NODES_PATH.format(
            bid_id=w["bid"], snapshot_id=applied["snapshot_id"], section_id=chapter["section_id"]
        ),
        params={
            "expected_snapshot_digest": applied["snapshot_digest"],
            "expected_section_digest": chapter["digest"],
        },
    )
    assert selected.status_code == 200, selected.text
    nodes = selected.json()
    if current:
        assert nodes["blocking_reasons"] == []
    else:
        assert "AUTHORING_PACKAGE_DRAFT_CHANGED" in nodes["blocking_reasons"]
    [node] = nodes["nodes"]
    assert node["node_type"] == "paragraph" and node["text"] == ""
    return {
        **nodes["target"],
        **{key: node[key] for key in ("node_id", "before_node_digest")},
    }


def build_structured_word(w):
    target = w["input_body"]["target_section"]
    saved = w["saved"]
    # Mirror AuthoringBuilds: an outlined snapshot must carry its two
    # selected frozen templates, not the legacy plain-writer request.
    base = f"/api/v1/bids/{w['bid']}"
    draft_path = f"{base}/drafts/{target['draft_id']}"
    gate = current_layout(w, draft_path, target["section_id"])
    assert gate["state"] == "structured_layout_rechecked"
    assert gate["ordinary_structure_protected"]
    assert gate["snapshot_id"] == saved["snapshot_id"]
    tree = w["client"].get(draft_path + "/structure")
    assert tree.status_code == 200, tree.text
    structure = tree.json()
    assert structure["snapshot_id"] == saved["snapshot_id"]
    started = request_build(
        w,
        body={
            "draft_id": target["draft_id"],
            "draft_revision": saved["draft_revision"],
            "follow_up": "none",
            "formats": ["docx"],
            "directory_template_version_id": structure["directory_template_version_id"],
            "style_template_version_id": structure["style_template_version_id"],
            "pagination_mode": "chapter_start_new_page",
        },
    )
    assert started.status_code == 202, started.text
    build_id = started.json()["resource_id"]
    with connection() as c:
        message = c.execute(
            "SELECT o.payload FROM design.builds b JOIN design.outbox o ON o.operation_id=b.operation_id "
            "WHERE b.id=%s AND o.topic='tender.task.export.v1'",
            (build_id,),
        ).fetchone()["payload"]
    lease = engine.acquire(message)
    assert lease is not None
    build = {"id": build_id, "message": message, "lease": lease}
    computed = compute(build)
    assert computed["snapshot_id"] == saved["snapshot_id"]
    [word] = computed["outputs"]
    raw = storage.get(word["object_key"])
    assert word["format"] == "docx" and sha(raw) == word["digest"]
    with ZipFile(BytesIO(raw)) as archive:
        body = archive.read("word/document.xml").decode()
        assert "施工进度与资源配置" in body and "质量管理与验收" in body
        assert "<w:p" in body and "<w:t" in body
    publish(build, computed)

    return build, word, body


def test_confirmed_outline_to_exact_chapter_and_editable_internal_word(adopted):
    # The existing fixtures save explicit fixed input, create a manual
    # template, launch one offline model call, then separately confirm adoption.
    w = adopted
    saved = w["saved"]
    journey = w["technical_journey"]
    target = w["input_body"]["target_section"]
    fixed = w["fixed"]["manifest"]["selection"]
    action = w["action_response"].json()["preview"]
    assert len(w["calls"]) == 1 and fixed["target_section"] == target
    assert target["section_id"] == journey["chapter"]["section_id"]
    assert target["snapshot_id"] == journey["snapshot"]["snapshot_id"]
    assert action["before"] == journey["chapter"]["content"]
    assert saved["draft_revision"] == target["base_draft_revision"] + 1

    frozen = w["client"].get(
        f"/api/v1/bids/{w['bid']}/work-contexts/draft_snapshot/{saved['snapshot_id']}"
    )
    assert frozen.status_code == 200, frozen.text
    sections = {item["section_id"]: item for item in frozen.json()["document"]["sections"]}
    assert sections[target["section_id"]]["content"] == action["after"]
    assert sections[journey["quality"]["section_id"]] == journey["quality"]

    build, word, body = build_structured_word(w)
    assert w["raw"]["replacement_text"] in body

    document = adoption_body(w, build)["member"]["document_version_id"]
    advisory = w["client"].post(
        f"/api/v1/bids/{w['bid']}/builds/{build['id']}/technical-docx-check",
        json={
            "document_version_id": document,
            "filename": "合成内部预览施组.docx",
            "prohibited_names": [],
        },
        headers=headers(w),
    )
    assert advisory.status_code == 200, advisory.text
    result = advisory.json()
    assert result["artifact_sha256"] == word["digest"]
    assert result["snapshot_id"] == saved["snapshot_id"]
    assert result["historical_advisory"] and not result["publication_authorized"]
    assert "CONTENT_AND_PROJECT_RULE_REVIEW" in result["manual_check_codes"]
    with connection() as c:
        assert not package_outputs.admitted(c, w["bid"], document)
        assert not c.execute(
            "SELECT 1 FROM design.submission_records WHERE bid_id=%s", (w["bid"],)
        ).fetchone()
    assert len(w["calls"]) == 1


def test_two_chapters_use_their_own_saved_baselines_and_one_internal_word(adopted, monkeypatch):
    first = adopted
    before = first["technical_journey"]
    initial = first["saved"]
    first_calls = first["calls"]
    first_text = first["raw"]["replacement_text"]
    first_proof = qualified(first)
    bid = first["bid"]
    chapter_path = f"/api/v1/bids/{bid}"
    chapter_id = before["quality"]["section_id"]
    stale_body = deepcopy(first["input_body"])
    stale_body["target_section"] = blank_target(
        first, before["snapshot"], before["quality"], current=False
    )
    rejected = save(first, body=stale_body)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    assert len(first_calls) == 1

    latest = first["client"].get(
        f"{chapter_path}/work-contexts/draft_snapshot/{initial['snapshot_id']}"
    )
    assert latest.status_code == 200, latest.text
    sections = {item["section_id"]: item for item in latest.json()["document"]["sections"]}
    assert sections[chapter_id] == before["quality"]
    pinned = deepcopy(first["input_body"])
    pinned["target_section"] = blank_target(first, initial, sections[chapter_id])
    assert pinned["target_section"]["snapshot_id"] != stale_body["target_section"]["snapshot_id"]
    assert (
        pinned["target_section"]["base_section_revision"]
        == stale_body["target_section"]["base_section_revision"]
    )

    second = case.__wrapped__({**first, "input_body": pinned}, monkeypatch)
    second["raw"]["replacement_text"] = "合成质量章：按已固定证据核对质量验收，不作合规结论。"
    template_path = f"{chapter_path}/task-definitions/{second['template']['id']}"
    quoted = second["client"].get(template_path + "/authoring-fee-quote")
    assert quoted.status_code == 200, quoted.text
    fee = quoted.json()
    assert fee["definition_version_id"] == second["template"]["version_id"]
    assert fee["estimate_not_provider_spend_cap"]
    assert not second["calls"]
    claimed = second["client"].post(
        template_path + "/runs",
        json={
            "rerun": False,
            "authoring_fee": {
                "price_version_id": fee["price_version_id"],
                "max_reserved_minor": fee["reserved_minor"],
            },
        },
        headers=headers(second, etag=fee["template_etag"]),
    )
    assert claimed.status_code == 202, claimed.text
    bind_task(second, claimed.json())
    assert not second["calls"]
    candidate = finish(second)
    assert candidate["state"] == "succeeded"
    assert candidate["result"]["section_id"] == chapter_id
    second["action_ref"] = candidate["result"]["action_ref"]
    second["action_response"] = second["client"].get(second["action_ref"])
    assert second["action_response"].status_code == 200, second["action_response"].text
    second["action_id"] = second["action_response"].json()["action_id"]
    second["adoption_key"] = uuid4().hex
    result = confirm(second)
    assert result.status_code == 200, result.text
    second["saved"] = result.json()["result"]["assistant_resolution"]["domain_result"]
    assert second["saved"]["draft_revision"] == initial["draft_revision"] + 1
    second_proof = qualified(second)
    assert second_proof["manifest"]["section_id"] == chapter_id
    assert second_proof["input_id"] != first_proof["input_id"]
    assert second_proof["section_revision_id"] != first_proof["section_revision_id"]
    with connection() as c:
        snapshot = c.execute(
            "SELECT manifest FROM design.draft_snapshots WHERE bid_id=%s AND id=%s",
            (bid, second["saved"]["snapshot_id"]),
        ).fetchone()["manifest"]
        proofs = snapshot["authoring_exact_sections"]["sections"]
        assert {item["qualification_digest"] for item in proofs} == {
            first_proof["digest"],
            second_proof["digest"],
        }

    build, _, text = build_structured_word(second)
    assert first_text in text and second["raw"]["replacement_text"] in text
    document = adoption_body(second, build)["member"]["document_version_id"]
    with connection() as c:
        assert not package_outputs.admitted(c, bid, document)
        assert not c.execute(
            "SELECT 1 FROM design.submission_records WHERE bid_id=%s", (bid,)
        ).fetchone()
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.task_runs WHERE bid_id=%s", (bid,)
            ).fetchone()["n"]
            == 2
        )
    assert len(first_calls) == len(second["calls"]) == 1
