"""B6 native atomicity acceptance; requires explicit isolated B5 PG17/S3 setup."""

# ruff: noqa: F401,F811
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from authoring_package_input_fixtures import ADMIN_DSN, world
from authoring_package_input_fixtures import exact as base_exact
from authoring_package_job_fixtures import case, current, finish, input_database, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import adopted
from test_authoring_exact_builds_pg import database as build_database
from test_authoring_exact_revisions_pg import confirm, published, qualified
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_exact_text_edits_pg import database as single_database
from test_authoring_exact_text_edits_pg import edit, request_body, unchanged
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers

from packages.authoring import exact_sources, exact_text_edit_service, exact_text_edits, repository
from packages.domain.runtime import ROOT, DomainError, connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B6 PG17 and real S3")


@pytest.fixture(scope="module")
def database(single_database):
    single_database["owner"].execute(
        (ROOT / "packages/contracts/sql/authoring-exact-multi-text-edits.sql").read_text()
    )
    return single_database


@pytest.fixture
def exact(requirements, monkeypatch):
    # Seed two real nodes BEFORE freezing inputs/adopting the candidate, never
    # manufacture an already-qualified revision or bypass append-only guards.
    original = repository.empty_content

    def two_nodes(name, ordinal):
        content = original(name, ordinal)
        content["content"].append(
            {
                "type": "paragraph",
                "attrs": {"id": str(uuid4())},
                "content": [{"type": "text", "text": "Synthetic unchanged second node"}],
            }
        )
        return content

    monkeypatch.setattr(repository, "empty_content", two_nodes)
    return base_exact.__wrapped__(requirements)


def body(w):
    q = qualified(w)
    with connection() as c:
        original = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s", (q["section_revision_id"],)
        ).fetchone()["content"]
    return {
        "protocol": "authoring-exact-multi-text-edit/1",
        "base_draft_revision": w["saved"]["draft_revision"],
        "section_revision_id": str(q["section_revision_id"]),
        "edits": [
            {
                "node_id": node["attrs"]["id"],
                "before_node_digest": sha(node),
                "replacement_text": f"Synthetic atomic edit {i}",
            }
            for i, node in enumerate(original["content"])
        ],
        "reason": "Synthetic explicit batch correction",
    }, original


def test_batch_commits_one_snapshot_replays_and_preserves_parent(adopted):
    w = adopted
    request, original = body(w)
    key = uuid4().hex
    saved = edit(w, request, key=key)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["protocol"] == "authoring-exact-text-edit-result/2"
    assert result["draft_revision"] == request["base_draft_revision"] + 1
    with connection() as c:
        assert (
            exact_sources.load(c, UUID(w["bid"]), UUID(result["section_revision_id"]))
            == result["qualification"]
        )
        rows = c.execute(
            "SELECT id,content FROM design.section_revisions WHERE id=ANY(%s::uuid[])",
            ([request["section_revision_id"], result["section_revision_id"]],),
        ).fetchall()
        contents = {str(row["id"]): row["content"] for row in rows}
        assert contents[request["section_revision_id"]] == original
        assert contents[result["section_revision_id"]] == exact_text_edits.materialize(
            original, request
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.authoring_exact_manual_revisions WHERE bid_id=%s",
                (w["bid"],),
            ).fetchone()["n"]
            == 1
        )
    replay = edit(w, request, key=key)
    assert replay.status_code == 200 and replay.json() == result
    changed = deepcopy(request)
    changed["edits"][1]["replacement_text"] = "different command body"
    assert edit(w, changed, key=key).status_code == 409
    assert edit(w, request).status_code == 412


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "digest", "foreign-revision", "metadata"]
)
def test_invalid_batch_changes_nothing(adopted, mutation):
    request, _ = body(adopted)
    if mutation == "duplicate":
        request["edits"][1] = request["edits"][0]
    elif mutation == "missing":
        request["edits"][1]["node_id"] = str(uuid4())
    elif mutation == "digest":
        request["edits"][1]["before_node_digest"] = "0" * 64
    elif mutation == "foreign-revision":
        request["section_revision_id"] = str(uuid4())
    else:
        request["edits"][1]["source_refs"] = []
    response = edit(adopted, request)
    assert response.status_code in {404, 412, 422}, response.text
    unchanged(adopted)


def test_concurrent_same_key_returns_one_batch_ack(adopted):
    request, _ = body(adopted)
    key = uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: edit(adopted, request, key=key), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()


def test_missing_audit_rolls_back_all_nodes_and_snapshot(adopted, monkeypatch):
    request, _ = body(adopted)
    monkeypatch.setattr(exact_text_edit_service, "audit", lambda *args: None)
    response = edit(adopted, request)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_actor_change_cannot_save_any_batch_node(adopted):
    request, _ = body(adopted)
    with pytest.raises(DomainError) as error:
        exact_text_edit_service.save(
            adopted["actor"],
            adopted["bid"],
            adopted["saved"]["draft_id"],
            uuid4().hex,
            repository.draft_etag(adopted["saved"]["draft_id"], request["base_draft_revision"]),
            request,
            final_auth=lambda: {"member_id": uuid4()},
        )
    assert error.value.code == "AUTHORING_EXACT_ACTOR_CHANGED"
    unchanged(adopted)


def test_v1_edit_can_extend_v2_lineage_without_rewriting_parent(adopted):
    request, _ = body(adopted)
    first = edit(adopted, request)
    assert first.status_code == 200, first.text
    adopted["saved"] = first.json()
    single = request_body(adopted, first.json()["qualification"])
    second = edit(adopted, single)
    assert second.status_code == 200, second.text
    assert (
        second.json()["qualification"]["manifest"]["protocol"]
        == "authoring-exact-manual-revision/1"
    )
    with connection() as c:
        assert (
            exact_sources.load(c, UUID(adopted["bid"]), UUID(first.json()["section_revision_id"]))
            == first.json()["qualification"]
        )
        assert (
            exact_sources.load(c, UUID(adopted["bid"]), UUID(second.json()["section_revision_id"]))
            == second.json()["qualification"]
        )
