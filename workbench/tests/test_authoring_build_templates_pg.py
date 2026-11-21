"""Native draft/template/build routes against a disposable PG17, with no render or model calls."""
# ruff: noqa: F401,F811

import os
from copy import deepcopy
from uuid import uuid4

import pytest
from authoring_history_fixtures import history_case
from test_authoring_package_adoptions_pg import database, env
from test_authoring_rich import cell, row, table
from work_context_catalog_fixtures import image_asset, save

from apps.api.authoring_structure import router as structure_router
from packages.domain.runtime import assert_role, etag

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires an isolated disposable PostgreSQL database",
)


@pytest.fixture
def case(history_case):
    assert_role()
    history_case["client"].app.include_router(structure_router)
    return history_case


def post(case, path, body, *, tag=None, key=None):
    headers = {
        "Origin": os.environ["APP_ORIGIN"],
        "X-CSRF-Token": case["csrf"],
        "Idempotency-Key": key or uuid4().hex,
    }
    if tag:
        headers["If-Match"] = tag
    return case["client"].post(path, json=body, headers=headers)


def accepted_build(case, body):
    response = post(case, f"/api/v1/bids/{case['bid']}/builds", body)
    assert response.status_code == 202, response.text
    build = case["client"].get(f"/api/v1/builds/{response.json()['resource_id']}")
    assert build.status_code == 200, build.text
    assert build.json()["identity"]["request"] == body
    return build.json()["identity"]


def test_default_draft_from_advertised_outline_freezes_both_templates_at_creation(case):
    client = case["client"]
    path = f"/api/v1/bids/{case['bid']}/drafts"
    capabilities = client.get("/api/v1/authoring/capabilities").json()
    outline = capabilities["default_outline_template_version_id"]
    created = post(
        case, path, {"title": "合成默认目录草稿", "outline_template_version_id": outline}
    )
    assert created.status_code == 201, created.text
    head = created.json()
    tree = client.get(f"{path}/{head['id']}/structure").json()
    assert tree["snapshot_id"] == head["snapshot_id"] and tree["draft_revision"] == 1
    assert tree["structure_version_id"] and tree["directory_template_version_id"] == outline
    assert tree["contains_tables_or_images"] is False
    build = accepted_build(
        case,
        {
            "draft_id": head["id"],
            "draft_revision": 1,
            "directory_template_version_id": outline,
            "style_template_version_id": tree["style_template_version_id"],
            "formats": ["docx", "pdf"],
            "follow_up": "none",
            "pagination_mode": "chapter_start_new_page",
        },
    )
    assert build["snapshot_id"] == head["snapshot_id"]


def test_legacy_text_and_rich_revision_four_recover_only_by_their_frozen_inputs(case):
    client = case["client"]
    base = f"/api/v1/bids/{case['bid']}"
    draft = f"{base}/drafts/{case['draft']}"
    text_tree = client.get(draft + "/structure").json()
    assert text_tree["structure_version_id"] is None
    assert text_tree["contains_tables_or_images"] is False
    simple = {
        "draft_id": str(case["draft"]),
        "draft_revision": 2,
        "template_version_id": client.get("/api/v1/authoring/capabilities").json()[
            "default_template_version_id"
        ],
        "formats": ["docx", "pdf"],
        "follow_up": "none",
    }
    text_build = accepted_build(case, simple)
    assert text_build["writer_kind"] == "strict_text/1"
    assert text_build["snapshot_id"] == text_tree["snapshot_id"]

    content = deepcopy(case["section"]["content"])
    grid = table(row(cell(), cell()), row(cell(), cell()))
    grid["attrs"]["column_widths_twips"] = [1800, 1800]
    content["content"].append(grid)
    assert save(case, content=content)["draft_revision"] == 3
    assert client.get(draft + "/structure").json()["contains_tables_or_images"] is True
    asset = image_asset(case)
    content["content"].append(
        {
            "type": "image",
            "attrs": {
                "id": uuid4().hex,
                "asset_id": asset["asset_id"],
                "asset_revision": asset["revision"],
                "asset_version_id": asset["id"],
                "width_twips": 2400,
                "height_twips": 2400,
                "alt": "合成图片",
                "caption": "原修订中的图片",
            },
        }
    )
    saved = save(case, content=content)
    assert saved["draft_revision"] == 4
    four = client.get(draft + "/structure").json()
    old_url = f"{base}/draft-snapshots/{saved['snapshot_id']}"
    original = client.get(old_url).json()
    assert four["structure_version_id"] is None and four["contains_tables_or_images"] is True
    assert original["sections"] == [content]
    assert original["authoring_images"]["items"][0]["asset_version_id"] == asset["id"]
    assert "authoring_structure" not in original

    downgraded = post(case, base + "/builds", simple | {"draft_revision": 4})
    assert (
        downgraded.status_code == 422
        and downgraded.json()["code"] == "AUTHORING_RICH_BUILD_REQUIRED"
    )
    dual = {
        "draft_id": str(case["draft"]),
        "draft_revision": 4,
        "directory_template_version_id": four["directory_template_version_id"],
        "style_template_version_id": four["style_template_version_id"],
        "formats": ["docx", "pdf"],
        "follow_up": "none",
        "pagination_mode": "chapter_start_new_page",
    }
    invented = post(case, base + "/builds", dual)
    assert (
        invented.status_code == 409
        and invented.json()["code"] == "BUILD_TEMPLATE_SNAPSHOT_MISMATCH"
    )

    tag = etag("draft", case["draft"], 4)
    preview = post(
        case,
        draft + "/style-template/preview",
        {
            "base_draft_revision": 4,
            "style_template_version_id": four["style_template_version_id"],
            "format_bindings": [],
            "format_review_ack": None,
        },
        tag=tag,
    )
    assert preview.status_code == 201, preview.text
    proposal = preview.json()
    assert proposal["before_sections"] == proposal["after_sections"]
    assert not proposal["created_ids"] and not proposal["deletion_impact"]
    assert client.get(draft + "/structure").json() == four
    resolve = f"{base}/authoring-structure-actions/{proposal['action_id']}/resolve"
    stale = post(case, resolve, {"decision": "confirm"}, tag=etag("draft", case["draft"], 3))
    assert stale.status_code == 412
    key = uuid4().hex
    confirmed = post(case, resolve, {"decision": "confirm"}, tag=tag, key=key)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["draft_revision"] == 5
    assert post(case, resolve, {"decision": "confirm"}, tag=tag, key=key).json() == confirmed.json()
    five = client.get(draft + "/structure").json()
    assert five["structure_version_id"] and five["snapshot_id"] == confirmed.json()["snapshot_id"]
    assert five["nodes"] == four["nodes"] and five["contains_tables_or_images"] is True
    pinned = client.get(f"{base}/draft-snapshots/{five['snapshot_id']}").json()
    assert pinned["sections"] == original["sections"]
    assert pinned["authoring_images"] == original["authoring_images"]
    assert pinned["authoring_structure"]["id"] == five["structure_version_id"]
    assert client.get(old_url).json() == original
    build = accepted_build(case, dual | {"draft_revision": 5})
    assert (
        build["writer_kind"] == "generated_rich/3" and build["snapshot_id"] == five["snapshot_id"]
    )
    assert build["snapshot_digest"] == pinned["snapshot_digest"]
