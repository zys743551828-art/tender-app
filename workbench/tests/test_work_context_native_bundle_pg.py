"""Optional synthetic native HTTP bundle for independent frontend contract checks.

Only the explicit WORK_CONTEXT_SYNTHETIC_RESPONSE_BUNDLE test path is written.
No auth headers, tokens, DSN, private object locator or live data are captured.
Existing A/B product modules and their frozen tests remain untouched.
"""
# ruff: noqa: F401,F811

import base64
import io
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_authoring_package_adoptions_pg import adopt, env
from test_authoring_rich import cell, paragraph, row, table
from test_authoring_rich_integration import register
from test_bid_package_submissions_pg import (
    api,
    catalog,
    database,
    inventory,
    requirements,
    uid,
    world,
)
from test_work_contexts_pg import TestExactRunContexts as _RunCases
from test_work_contexts_pg import build_client, forbid_io
from work_context_catalog_fixtures import (
    catalog_app,
    client_for,
    complete_build,
    current,
    path,
    queue_build,
    save,
)

from apps.api.authoring_rich import router as rich_router
from packages.authoring import rich_images
from packages.domain.runtime import sha

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated synthetic native response bundle PostgreSQL 17 required",
)


@pytest.fixture(scope="module", autouse=True)
def bundle():
    result = {"version": "synthetic-work-context-http-bundle/1", "synthetic": True, "responses": []}
    yield result
    location = os.environ.get("WORK_CONTEXT_SYNTHETIC_RESPONSE_BUNDLE")
    if location:
        target = Path(location)
        assert target.is_absolute() and target.parent.is_dir()
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        assert '"object_key"' not in encoded and '"idempotency_key"' not in encoded
        target.write_text(encoded + "\n")


def capture(bundle, client, label, url, **kwargs):
    response = client.get(url, **kwargs)
    assert response.status_code == 200, response.text
    body = response.json()
    # Response JSON is stored without changing any data/digest/timestamp/UUID.
    bundle["responses"].append(
        {"label": label, "path": str(response.request.url), "status": 200, "body": body}
    )
    return body


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestNativePackageResponses:
    original_case = _RunCases.original_case
    frozen_case = _RunCases.frozen_case
    execution_case = _RunCases.execution_case
    prepared_case = _RunCases.prepared_case
    exact_inventory_proof_case = _RunCases.exact_inventory_proof_case
    launch_case = _RunCases.launch_case
    post = _RunCases.post
    launch = _RunCases.launch
    message = _RunCases.message
    provider = _RunCases.provider
    equivalent_case = _RunCases.equivalent_case
    finish = _RunCases.finish
    completed = _RunCases.completed
    bind_submission = _RunCases.bind_submission

    def test_capture_exact_run_submission_and_their_native_directories(
        self, completed, monkeypatch, bundle
    ):
        case = completed
        submission = self.bind_submission(case, case["run"])
        forbid_io(monkeypatch)
        with client_for(case["w"]["client"]) as client:
            bid = case["scope"][0]
            capture(
                bundle,
                client,
                "package_review_run",
                path(bid, "package_review_run", case["run"]["id"]),
            )
            capture(
                bundle,
                client,
                "package_submission",
                path(bid, "package_submission", submission["id"]),
            )
            for kind in ("package_review_run", "package_submission"):
                capture(
                    bundle, client, "choices_" + kind, path(bid, "choices"), params={"kind": kind}
                )


def test_capture_native_plain_sparse_rich_snapshot_build_and_adoption(env, build_client, bundle):
    identity, message = queue_build(env, ("docx", "pdf"))
    complete_build(message)
    with client_for(build_client) as client:
        plain = capture(
            bundle,
            client,
            "draft_snapshot",
            path(env["bid"], "draft_snapshot", env["saved"]["snapshot_id"]),
        )
        built = capture(bundle, client, "build", path(env["bid"], "build", identity))
    output = next(item for item in built["build"]["outputs"] if item["format"] == "docx")
    adopt(
        env,
        identity,
        {
            "snapshot_id": env["saved"]["snapshot_id"],
            "snapshot_digest": plain["selection"]["snapshot_digest"],
            "package_id": None,
            "member": {
                "member_id": "native-contract-word",
                "document_version_id": output["document"]["document_version_id"],
                "purposes": ["technical"],
                "parts": [],
            },
            "reason": "Explicit synthetic native response fixture",
        },
    )
    with client_for(build_client) as client:
        capture(
            bundle,
            client,
            "build_relations",
            path(env["bid"], "build", identity) + "/relations",
            params={"target": "package_revision"},
        )

    # The original core saved-content path allows distinct sparse ordinals before
    # adopting the explicit tree. Preserve those bytes and the display ordering.
    _, section = current(env)
    content = deepcopy(section["content"])
    content["attrs"]["ordinal"] = 7
    sparse = save(env, content=content)
    with client_for(build_client) as client:
        value = capture(
            bundle,
            client,
            "draft_snapshot_sparse_ordinal",
            path(env["bid"], "draft_snapshot", sparse["snapshot_id"]),
        )
    assert value["document"]["outline"] is None
    assert value["document"]["sections"][0]["ordinal"] == 0
    assert value["document"]["sections"][0]["content"]["attrs"]["ordinal"] == 7

    stream = io.BytesIO()
    with Image.frombytes("RGB", (4, 4), uuid4().bytes * 3) as raster:
        raster.save(stream, format="PNG")
    raw = stream.getvalue()
    normalized = rich_images.normalize(raw, "image/png")

    def descriptor(data, name):
        key = f"authoring-images/{env['bid']}/{uuid4()}/{name}"
        env["objects"][key] = data
        return {
            "digest": sha(data),
            "byte_size": len(data),
            "object_key": key,
            "media_type": "image/png",
        }

    asset, _, _, _ = register(
        env
        | {
            "original": descriptor(raw, "original"),
            "normalized": descriptor(normalized["bytes"], "normalized"),
            "proof": normalized["proof"],
        }
    )
    content["attrs"]["ordinal"] = 0
    content["content"] = [
        paragraph("原生保存的完整合成正文。" * 15000),
        table(row(cell(2, 2), cell()), row(cell())),
        {
            "type": "image",
            "attrs": {
                "id": uuid4().hex,
                "asset_id": asset["asset_id"],
                "asset_revision": asset["revision"],
                "asset_version_id": asset["id"],
                "width_twips": 2400,
                "height_twips": 2400,
                "alt": "合成原生图像",
                "caption": "真实规范化版本",
            },
        },
    ]
    rich = save(env, content=content)
    app = catalog_app()
    app.include_router(rich_router)
    with TestClient(app) as client:
        client.cookies.update(build_client.cookies)
        capture(
            bundle,
            client,
            "draft_snapshot_rich",
            path(env["bid"], "draft_snapshot", rich["snapshot_id"]),
        )
        for kind in ("draft_snapshot", "build"):
            capture(
                bundle,
                client,
                "choices_" + kind,
                path(env["bid"], "choices"),
                params={"kind": kind},
            )
        capture(
            bundle,
            client,
            "historical_image_metadata",
            f"/api/v1/bids/{env['bid']}/authoring-images/{asset['asset_id']}/versions/{asset['id']}",
        )
    bundle["synthetic_normalized_image"] = {
        "asset_id": asset["asset_id"],
        "asset_version_id": asset["id"],
        "sha256": sha(normalized["bytes"]),
        "base64": base64.b64encode(normalized["bytes"]).decode(),
        "media_type": "image/png",
    }
