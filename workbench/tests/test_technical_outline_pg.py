"""Real authenticated HTTP, scoped authoring transactions and native PostgreSQL heads."""
# ruff: noqa: F401,F811

import pytest
from test_bid_package_api import world
from test_bid_package_requirements_api import database, inventory, prepare_requirements, pytestmark
from test_stable_lot_identity import api, headers, uid


def preview_client(world):
    w = prepare_requirements(world, statement="施工工期与进度：检查合成要求")
    saved = inventory(w)
    assert saved.status_code == 201, saved.text
    selected = saved.json()
    bid_id = w["scope"].bid_id
    client = w["client"]
    paths = f"/api/v1/bids/{bid_id}"
    created = client.post(
        paths + "/drafts",
        json={"title": "仅测试技术标大纲", "outline_template_version_id": None},
        headers=headers(w),
    )
    assert created.status_code == 201, created.text
    draft = created.json()["id"]
    draft_path = paths + "/drafts/" + draft
    rev = created.json()["revision"]
    tag = created.headers["etag"]

    def ref(package):
        m = package["manifest"]
        return {
            "package_id": m["package_id"],
            "revision_id": m["revision_id"],
            "digest": package["digest"],
        }

    request = {
        "base_draft_revision": rev,
        "basis": {
            "target": ref(w["own"]),
            "authority": ref(w["authority_package"]),
            "inventory": {"id": selected["manifest"]["id"], "digest": selected["digest"]},
        },
        "chapter_keys": ["schedule"],
    }
    endpoint = draft_path + "/technical-outline/preview"
    return w, (client, paths, draft_path, tag, rev, endpoint, request, saved)


@pytest.mark.parametrize("change", ["new_inventory", "source_withdrawn", "after_commit"])
def test_exact_outline_requires_live_basis_and_preserves_read_back_of_committed_outline(
    world, change
):
    w, (client, paths, draft_path, tag, rev, endpoint, request, saved) = preview_client(world)
    generic = client.post(
        draft_path + "/structure/preview",
        json={
            "base_draft_revision": rev,
            "changes": [
                {
                    "op": "add",
                    "client_key": f"technical-bid-{'a' * 64}-schedule",
                    "title": "任意标题",
                    "node_type": "chapter",
                    "parent": None,
                    "ordinal": 1,
                }
            ],
        },
        headers=headers(w, etag=tag),
    )
    assert (
        generic.status_code == 409
        and generic.json()["code"] == "TECHNICAL_OUTLINE_PREVIEW_REQUIRED"
    )
    foreign = client.post(
        endpoint,
        json={
            **request,
            "basis": {
                **request["basis"],
                "authority": {
                    **request["basis"]["authority"],
                    "package_id": uid(),
                },
            },
        },
        headers=headers(w, etag=tag),
    )
    assert foreign.status_code == 409 and foreign.json()["code"] == "TECHNICAL_OUTLINE_BASIS_STALE"
    assert client.get(draft_path).json()["revision"] == rev
    preview_key, apply_key = uid(), uid()
    proposed = client.post(endpoint, json=request, headers=headers(w, key=preview_key, etag=tag))
    assert proposed.status_code == 201, proposed.text
    value = proposed.json()
    [chapter] = value["created_ids"].values()
    new = value["after_sections"][chapter]
    assert new["attrs"]["title"] == "施工进度与资源配置"
    assert not new["attrs"]["rule_ids"] and not new["attrs"]["source_refs"]
    assert not new["content"][0]["content"]
    assert all(
        value["after_sections"][key] == text for key, text in value["before_sections"].items()
    )
    path = paths + "/authoring-structure-actions/" + value["action_id"] + "/resolve"

    def resolve(decision, key=apply_key):
        return client.post(path, json={"decision": decision}, headers=headers(w, key=key, etag=tag))

    if change == "after_commit":
        adopted = resolve("confirm")
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["draft_revision"] == rev + 1
    if change == "source_withdrawn":
        w["database"]["owner"].execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (w["sources"][-1],),
        )
    else:
        superseding = inventory(w, tag=saved.headers["etag"])
        assert superseding.status_code == 201, superseding.text
    replay = client.post(endpoint, json=request, headers=headers(w, key=preview_key, etag=tag))
    assert replay.json() == value and replay.headers["Idempotent-Replayed"] == "true"
    confirm = resolve("confirm")
    if change == "after_commit":
        assert confirm.json() == adopted.json() and confirm.headers["Idempotent-Replayed"] == "true"
    else:
        assert (
            confirm.status_code == 409 and confirm.json()["code"] == "TECHNICAL_OUTLINE_BASIS_STALE"
        )
        cancelled = resolve("reject", uid())
        assert cancelled.status_code == 200 and cancelled.json()["state"] == "rejected"
    assert client.get(draft_path).json()["revision"] == rev + (change == "after_commit")
    owner = w["database"]["owner"]
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.operations WHERE bid_id=%s", (w["scope"].bid_id,)
        ).fetchone()["n"]
        == 0
    )
