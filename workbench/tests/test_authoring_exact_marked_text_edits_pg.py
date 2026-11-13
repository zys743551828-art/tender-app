"""B7 synthetic marked-leaf acceptance on real non-owner PG17/private S3."""

# ruff: noqa: F401,F811
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, world
from authoring_package_input_fixtures import exact as base_exact
from authoring_package_job_fixtures import case, current, finish, input_database, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import adopted, compute, publish, start
from test_authoring_exact_builds_pg import database as build_database
from test_authoring_exact_revisions_pg import confirm, published, qualified
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_exact_text_edits_pg import database as single_database
from test_authoring_exact_text_edits_pg import edit, request_body, unchanged
from test_authoring_package_inputs_pg import mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers

from packages.authoring import (
    exact_marked_text_edits,
    exact_sources,
    exact_text_edit_service,
    exact_text_edits,
    repository,
)
from packages.domain import storage
from packages.domain.runtime import ROOT, Command, DomainError, connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B7 PG17 and real S3")


@pytest.fixture(scope="module")
def database(single_database):
    owner = single_database["owner"]
    owner.execute(
        (ROOT / "packages/contracts/sql/authoring-exact-multi-text-edits.sql").read_text()
    )
    with connection() as c:
        assert not exact_marked_text_edits.available(c)
    owner.execute(
        (ROOT / "packages/contracts/sql/authoring-exact-marked-text-edits.sql").read_text()
    )
    with connection() as c:
        assert exact_marked_text_edits.available(c)
    return single_database


@pytest.fixture
def exact(requirements, monkeypatch):
    original = repository.empty_content

    def marked_and_plain(name, ordinal):
        content = original(name, ordinal)
        # This is BEFORE freezing/adoption: no fabricated qualified history.
        for i in range(2):
            content["content"].append(
                {
                    "type": "paragraph",
                    "attrs": {"id": str(uuid4())},
                    "content": [{"type": "text", "text": f"Synthetic plain node {i}"}],
                }
            )
        content["content"][1]["content"][0]["marks"] = [{"type": "italic"}, {"type": "bold"}]
        return content

    monkeypatch.setattr(repository, "empty_content", marked_and_plain)
    return base_exact.__wrapped__(requirements)


def body(w, q=None, *, plain=False):
    q = q or qualified(w)
    m = q["manifest"]
    with connection() as c:
        original = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s", (m["section_revision_id"],)
        ).fetchone()["content"]
    node = original["content"][0 if plain else 1]
    request = {
        "base_draft_revision": w["saved"]["draft_revision"],
        "section_revision_id": m["section_revision_id"],
        "node_id": node["attrs"]["id"],
        "before_node_digest": sha(node),
        "replacement_text": "Synthetic human replacement retaining original marks",
        "reason": "Synthetic explicit correction, not model/real-document acceptance",
    }
    if not plain:
        request["protocol"] = "authoring-exact-marked-text-edit/1"
    return request, original


def test_marked_commit_replay_preserves_exact_content_and_history(adopted):
    w = adopted
    root = qualified(w)
    request, original = body(w)
    parent_section = w["client"].get(f"/api/v1/sections/{root['section_id']}").json()
    parent_status = (
        w["client"]
        .get(
            f"/api/v1/bids/{w['bid']}/authoring/drafts/{w['saved']['draft_id']}/exact-qualification"
        )
        .json()
    )
    key = str(uuid4())
    response = edit(w, request, key=key)
    assert response.status_code == 200, response.text
    result = response.json()
    capabilities = w["client"].get("/api/v1/authoring/exact-marked-text-edit-capabilities")
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json()["protocol"] == "authoring-exact-text-edit-capabilities/3"
    assert capabilities.json()["available"] is True
    old_caps = w["client"].get("/api/v1/authoring/exact-text-edit-capabilities")
    assert old_caps.status_code == 200
    assert old_caps.json()["protocol"] == "authoring-exact-text-edit-capabilities/2"
    status = w["client"].get(
        f"/api/v1/bids/{w['bid']}/authoring/drafts/{w['saved']['draft_id']}/exact-qualification"
    )
    assert status.status_code == 200, status.text
    assert (
        status.json()["exact_sections"][0]["qualification_id"]
        == result["qualification"]["manifest"]["id"]
    )
    assert result["protocol"] == "authoring-exact-text-edit-result/3"
    assert result["qualification"]["manifest"]["origin"]["preserved_marks_digest"] == sha(
        original["content"][1]["content"][0]["marks"]
    )
    with connection() as c:
        assert (
            exact_sources.load(c, UUID(w["bid"]), UUID(result["section_revision_id"]))
            == result["qualification"]
        )
        assert qualified(w) == root
        actual = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s",
            (result["section_revision_id"],),
        ).fetchone()["content"]
        expected = deepcopy(original)
        expected["content"][1]["content"][0]["text"] = request["replacement_text"]
        assert actual == expected
    fixture = os.environ.get("FUSION_AUTHORING_MARKED_TEXT_EDIT_FIXTURE_PATH")
    if fixture:
        Path(fixture).write_text(
            json.dumps(
                {
                    "fixture_kind": "synthetic source/model content; native non-owner PG17/API/Worker/private S3",
                    "member_id": w["actor"],
                    "bid_id": w["bid"],
                    "parent_section": parent_section,
                    "parent_status": parent_status,
                    "parent_qualification": {
                        "manifest": root["manifest"],
                        "digest": root["digest"],
                    },
                    "request": request,
                    "request_key": key,
                    "request_etag": repository.draft_etag(
                        w["saved"]["draft_id"], request["base_draft_revision"]
                    ),
                    "ack": result,
                    "ack_etag": response.headers["etag"],
                    "capabilities": capabilities.json(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    replay = edit(w, request, key=key)
    assert replay.status_code == 200 and replay.json() == result
    assert replay.headers["etag"] == response.headers["etag"]
    changed = {**request, "replacement_text": "Different replacement"}
    assert edit(w, changed, key=key).status_code == 409
    assert edit(w, request).status_code == 412


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_marked_save_is_atomic(adopted, same_key):
    request, _ = body(adopted)
    key = uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(
            pool.map(
                lambda _: edit(adopted, request, key=key if same_key else uuid4().hex), range(2)
            )
        )
    statuses = sorted(r.status_code for r in replies)
    assert statuses == ([200, 200] if same_key else [200, 412]), [r.text for r in replies]
    if same_key:
        assert replies[0].json() == replies[1].json()
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.authoring_exact_manual_revisions WHERE bid_id=%s",
                (adopted["bid"],),
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("version", [1, 2])
def test_plain_then_marked_then_plain_chain_and_word_build(adopted, version):
    w = adopted
    request, original = body(w, plain=True)
    if version == 2:
        request = {
            "protocol": "authoring-exact-multi-text-edit/1",
            "base_draft_revision": request["base_draft_revision"],
            "section_revision_id": request["section_revision_id"],
            "edits": [
                {
                    "node_id": n["attrs"]["id"],
                    "before_node_digest": sha(n),
                    "replacement_text": f"Synthetic plain correction {i}",
                }
                for i, n in enumerate([original["content"][0], original["content"][2]])
            ],
            "reason": request["reason"],
        }
    first = edit(w, request)
    assert first.status_code == 200, first.text
    w["saved"] = first.json()
    marked, _ = body(w, first.json()["qualification"])
    second = edit(w, marked)
    assert second.status_code == 200, second.text
    w["saved"] = second.json()
    plain, _ = body(w, second.json()["qualification"], plain=True)
    plain["replacement_text"] = "Synthetic subsequent plain correction"
    third = edit(w, plain)
    assert third.status_code == 200, third.text
    w["saved"] = third.json()
    with connection() as c:
        for response in (first, second, third):
            result = response.json()
            assert (
                exact_sources.load(c, UUID(w["bid"]), UUID(result["section_revision_id"]))
                == result["qualification"]
            )
    build = start(w)
    output = compute(build)
    raw = storage.get(output["outputs"][0]["object_key"])
    with ZipFile(io.BytesIO(raw)) as archive:
        xml = archive.read("word/document.xml").decode()
        assert marked["replacement_text"] in xml and plain["replacement_text"] in xml
        # Generated local test output only, not untrusted source XML.
        document = ElementTree.fromstring(xml)  # nosec B314
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        runs = [
            run
            for run in document.findall(".//w:r", ns)
            if "".join(node.text or "" for node in run.findall("w:t", ns))
            == marked["replacement_text"]
        ]
        assert len(runs) == 1
        for mark in ("b", "i"):
            style = runs[0].find(f"w:rPr/w:{mark}", ns)
            assert style is not None
            assert style.get("{" + ns["w"] + "}val") not in {"0", "false", "off"}
    publish(build, output)


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_replay_survives_revocation_but_new_marked_save_fails(adopted, change):
    request, _ = body(adopted)
    key = uuid4().hex
    saved = edit(adopted, request, key=key)
    assert saved.status_code == 200, saved.text
    mutate_authority(adopted, change)
    replay = edit(adopted, request, key=key)
    assert replay.status_code == 200 and replay.json() == saved.json()
    adopted["saved"] = saved.json()
    newer, _ = body(adopted, saved.json()["qualification"])
    newer["replacement_text"] = "Synthetic forbidden new change"
    assert edit(adopted, newer).status_code == 409


@pytest.mark.parametrize("mutation", ["marks", "attrs", "source"])
def test_sql_rejects_forged_content_even_when_python_check_is_bypassed(
    adopted, monkeypatch, mutation
):
    real = exact_marked_text_edits.materialize

    def forged(content, request):
        result = real(content, request)
        if mutation == "marks":
            result["content"][1]["content"][0]["marks"].reverse()
        elif mutation == "attrs":
            result["content"][2]["attrs"]["id"] = str(uuid4())
        else:
            result["attrs"]["source_refs"] = []
        return result

    monkeypatch.setattr(exact_marked_text_edits, "materialize", forged)
    request, _ = body(adopted)
    response = edit(adopted, request)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_missing_audit_rolls_back_marked_revision(adopted, monkeypatch):
    monkeypatch.setattr(exact_text_edit_service, "audit", lambda *args: None)
    request, _ = body(adopted)
    response = edit(adopted, request)
    assert response.status_code == 409, response.text
    unchanged(adopted)


@pytest.mark.parametrize("worker", [False, True])
def test_private_checker_cannot_be_called_by_runtime_roles(adopted, worker):
    request, _ = body(adopted)
    with connection(worker) as c:
        assert not c.execute(
            "SELECT has_function_privilege(current_user,'design.authoring_exact_check_marked_text_record(uuid)','EXECUTE') AS granted"
        ).fetchone()["granted"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection(worker) as c:
            c.execute(
                "SELECT design.authoring_exact_check_marked_text_record(%s)",
                (request["section_revision_id"],),
            )


def test_missing_b7_fails_closed_without_affecting_old_capability(adopted, database):
    owner = database["owner"]
    owner.execute(
        "ALTER FUNCTION design.authoring_exact_check_marked_text_record(uuid) RENAME TO b7_temporarily_unavailable"
    )
    try:
        request, _ = body(adopted)
        assert edit(adopted, request).status_code == 503
        with connection() as c:
            assert not exact_marked_text_edits.available(c)
            assert exact_text_edits.available(c)
        unchanged(adopted)
    finally:
        owner.execute(
            "ALTER FUNCTION design.b7_temporarily_unavailable(uuid) RENAME TO authoring_exact_check_marked_text_record"
        )


@pytest.mark.parametrize("part", ["body", "etag", "status"])
def test_sql_rejects_forged_ack_and_rolls_back(adopted, monkeypatch, part):
    finish_command = Command.finish

    def forged(self, body, status=200, headers=None):
        body, headers = deepcopy(body), deepcopy(headers)
        if part == "body":
            body["section_digest"] = "0" * 64
        elif part == "etag":
            headers["ETag"] = '"draft:forged:999"'
        else:
            status = 201
        return finish_command(self, body, status, headers)

    monkeypatch.setattr(Command, "finish", forged)
    request, _ = body(adopted)
    response = edit(adopted, request)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_cross_bid_route_cannot_edit_marked_revision(adopted):
    request, _ = body(adopted)
    other = {**adopted, "bid": str(uuid4())}
    response = edit(other, request)
    assert response.status_code in {403, 404}, response.text
    unchanged(adopted)


@pytest.mark.parametrize("text", ["\u00a0", "\u0085", "\u202f", "\ufeff", "\ufeff \u00a0"])
def test_sql_independently_rejects_unicode_blank_replacements(adopted, monkeypatch, text):
    request, _ = body(adopted)
    request["replacement_text"] = text

    def forged(original, request):
        result = deepcopy(original)
        result["content"][1]["content"][0]["text"] = request["replacement_text"]
        return result

    monkeypatch.setattr(exact_marked_text_edits, "materialize", forged)
    response = edit(adopted, request)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_nonblank_unicode_spacing_is_not_normalized(adopted):
    request, original = body(adopted)
    request["replacement_text"] = "\u00a0\ufeffActual wording\u202f\u0085"
    response = edit(adopted, request)
    assert response.status_code == 200, response.text
    expected = deepcopy(original)
    expected["content"][1]["content"][0]["text"] = request["replacement_text"]
    with connection() as c:
        actual = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s",
            (response.json()["section_revision_id"],),
        ).fetchone()["content"]
        assert actual == expected


@pytest.mark.parametrize("reason", ["\u00a0", "\u0085", "\ufeff \u202f", "word\x7f"])
def test_sql_independently_rejects_invalid_reason(adopted, monkeypatch, reason):
    request, _ = body(adopted)
    request["reason"] = reason

    def forged(original, request):
        result = deepcopy(original)
        result["content"][1]["content"][0]["text"] = request["replacement_text"]
        return result

    monkeypatch.setattr(exact_marked_text_edits, "materialize", forged)
    response = edit(adopted, request)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_reason_tab_newline_and_c1_are_preserved(adopted):
    request, _ = body(adopted)
    request["reason"] = "\tActual explanation\nwith C1 \u0085\u009f and BOM \ufeff"
    response = edit(adopted, request)
    assert response.status_code == 200, response.text
    assert response.json()["qualification"]["manifest"]["origin"]["reason"] == request["reason"]
