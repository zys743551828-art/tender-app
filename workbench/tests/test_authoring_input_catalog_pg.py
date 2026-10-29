"""Actual PG17/API/S3 roundtrip; upstream originals and parse content are synthetic."""
# ruff: noqa: F401,F811

import json
import os
import socket
import threading
import time
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import httpx
import psycopg
import pytest
import uvicorn
from authoring_input_catalog_fixtures import ADMIN_DSN, database, exact, save, world
from psycopg.rows import dict_row
from test_authoring_package_inputs_pg import add_new_parse, mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers, uid

from deploy.authoring_input_catalog_readiness import verify
from packages.assistant.generation import nodes as stable_nodes
from packages.authoring import package_input_observation
from packages.authoring_input_catalog import facts, policy, service
from packages.contracts import authoring_input_catalog_api as contract
from packages.domain import storage
from packages.domain.bid_package_service import lock_bid
from packages.domain.human_decisions import append_decision
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import DomainError, connection, etag

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="explicit isolated PG17 and real S3 required")


def paths(w):
    t = w["input_body"]["target_section"]
    base = f"/api/v1/bids/{w['bid']}/authoring/input-catalog"
    return base, f"{base}/draft-snapshots/{t['snapshot_id']}/sections/{t['section_id']}/nodes"


def node_params(w):
    t = w["input_body"]["target_section"]
    return {
        "expected_snapshot_digest": t["snapshot_digest"],
        "expected_section_digest": t["section_digest"],
    }


def fact_params(w):
    body = w["input_body"]
    with connection() as c:
        digest = c.execute(
            "SELECT digest FROM design.fact_sets WHERE bid_id=%s AND id=%s",
            (w["bid"], body["facts"]["fact_set_id"]),
        ).fetchone()["digest"]
    return {
        "expected_fact_set_digest": digest,
        "fact_head_revision": body["facts"]["fact_head_revision"],
        **{
            f"{role}_{key}": value
            for role in ("target", "authority")
            for key, value in body["package_context"][role].items()
        },
    }


def read_nodes(w):
    response = w["client"].get(paths(w)[1], params=node_params(w))
    assert response.status_code == 200, response.text
    return response.json()


def read_facts(w, **extra):
    path = f"{paths(w)[0]}/fact-sets/{w['input_body']['facts']['fact_set_id']}/facts"
    return w["client"].get(path, params={**fact_params(w), **extra})


def no_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("catalog discovery cannot use storage or model I/O")

    monkeypatch.setattr(storage, "get", forbidden)
    monkeypatch.setattr(storage, "client", forbidden)
    monkeypatch.setattr(DeepSeekClient, "from_env", forbidden)


def counts(w):
    return (
        w["database"]["owner"]
        .execute(
            """SELECT (SELECT count(*) FROM design.commands) AS commands,
        (SELECT count(*) FROM design.audit_entries) AS audits,
        (SELECT count(*) FROM design.operations) AS operations,
        (SELECT count(*) FROM design.model_calls) AS calls,
        (SELECT count(*) FROM design.authoring_package_inputs) AS inputs"""
        )
        .fetchone()
    )


def test_native_catalog_exact_selection_parity_and_existing_save_roundtrip(exact, monkeypatch):
    w = exact
    before = counts(w)
    with monkeypatch.context() as patch:
        no_io(patch)
        node = read_nodes(w)
        assert node["blocking_reasons"] == [] and node["whole_snapshot_plain"]
        actual = stable_nodes(node["section_content"])
        assert node["nodes"][0]["node_id"] == actual[0]["node_id"]
        assert node["nodes"][0]["before_node_digest"] == actual[0]["before_digest"]
        response = read_facts(w)
        assert response.status_code == 200, response.text
        fact = response.json()
        assert fact["head_matches"] and fact["package_identity_matches"]
        assert fact["blocking_reasons"] == [] and len(fact["items"]) == 5
        assert all(
            r["provenance_status"] == "verified" and not r["facts_qualified"] for r in fact["items"]
        )
        assert len(fact["subject_choices"]) == 4
        assert counts(w) == before
    with service.snapshot("facts") as c:
        selection, identity = package_input_observation.selected_packages(
            c, w["bid"], w["input_body"]
        )
        documents = package_input_observation.documents(c, w["bid"], selection)
        original = package_input_observation.facts(
            c, w["bid"], w["input_body"], documents, identity, service.at(c)
        )
    assert {r["fact_id"]: r["fact_item_digest"] for r in fact["items"]} == {
        r["item"]["fact"]["id"]: r["item_digest"] for r in original["items"]
    }
    body = deepcopy(w["input_body"])
    body["target_section"] = {
        **node["target"],
        **{key: node["nodes"][0][key] for key in ("node_id", "before_node_digest")},
    }
    selected_use = body["facts"]["uses"][0]
    selected_use["fact_item_digest"] = next(
        f["fact_item_digest"] for f in fact["items"] if f["fact_id"] == selected_use["fact_id"]
    )
    assert body == w["input_body"]
    key = uid()
    saved = save(w, body=body, key=key)
    assert saved.status_code == 201, saved.text
    assert saved.json()["manifest"]["selection"] == body
    replay = save(w, body=body, key=key)
    assert replay.json() == saved.json() and replay.headers["Idempotent-Replayed"] == "true"
    assert counts(w)["inputs"] == before["inputs"] + 1


def test_runtime_is_nonowner_rr_read_only_and_no_new_schema_or_grants(database, exact):
    ready = verify()
    assert ready["ready"] and not ready["ddl_applied"]
    for result in ready["checks"].values():
        role = result["role"]
        assert role["read_only"] == "on" and role["isolation"] == "repeatable read"
        assert not role["owns"] and not role["rolsuper"]
    with psycopg.connect(database["worker_dsn"], row_factory=dict_row) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with pytest.raises(DomainError) as error:
            from packages.authoring_input_catalog.permissions import require

            require(c, "sets")
        assert error.value.code.endswith("ROLE_REJECTED")


@pytest.mark.parametrize("kind", ["nodes", "sets", "facts"])
def test_missing_api_select_fails_closed_without_owner_fallback(exact, kind):
    table = {
        "nodes": "design.draft_snapshots",
        "sets": "design.fact_sets",
        "facts": "design.audit_entries",
    }[kind]
    owner = exact["database"]["owner"]
    from psycopg import sql

    identifier = sql.Identifier(*table.split("."))
    owner.execute(sql.SQL("REVOKE SELECT ON {} FROM tender_api").format(identifier))
    try:
        if kind == "nodes":
            response = exact["client"].get(paths(exact)[1], params=node_params(exact))
        elif kind == "sets":
            response = exact["client"].get(paths(exact)[0] + "/fact-sets")
        else:
            response = read_facts(exact)
        assert response.status_code == 503 and response.json()["code"].endswith("UNAVAILABLE"), (
            response.text
        )
    finally:
        owner.execute(sql.SQL("GRANT SELECT ON {} TO tender_api").format(identifier))


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate",
        "unknown",
        "missing_digest",
        "wrong_digest",
        "wrong_bid",
        "wrong_set",
        "wrong_package",
        "swapped_kind",
    ],
)
def test_fact_query_closed_and_exact_without_latest_fallback(exact, attack):
    w = exact
    path = f"{paths(w)[0]}/fact-sets/{w['input_body']['facts']['fact_set_id']}/facts"
    params = fact_params(w)
    expected = 422
    if attack == "duplicate":
        params = list(params.items()) + [("fact_head_revision", params["fact_head_revision"])]
    elif attack == "unknown":
        params["latest"] = "true"
    elif attack == "missing_digest":
        del params["expected_fact_set_digest"]
    elif attack == "wrong_digest":
        params["expected_fact_set_digest"] = "0" * 64
        expected = 412
    elif attack == "wrong_bid":
        path = path.replace(w["bid"], uid())
        expected = 404
    elif attack == "wrong_set":
        path = path.replace(w["input_body"]["facts"]["fact_set_id"], uid())
        expected = 404
    elif attack == "wrong_package":
        params["target_package_id"] = uid()
        expected = 404
    else:
        for suffix in ("package_id", "revision_id", "manifest_digest"):
            params["target_" + suffix], params["authority_" + suffix] = (
                params["authority_" + suffix],
                params["target_" + suffix],
            )
        expected = 412
    before = counts(w)
    response = w["client"].get(path, params=params)
    assert response.status_code == expected, response.text
    assert counts(w) == before


def test_nodes_query_closed_and_cross_snapshot_and_digest_binding(exact):
    path, params = paths(exact)[1], node_params(exact)
    for extra in (
        [("latest", "true")],
        [("expected_snapshot_digest", params["expected_snapshot_digest"])],
    ):
        assert exact["client"].get(path, params=[*params.items(), *extra]).status_code == 422
    assert (
        exact["client"]
        .get(path, params={"expected_section_digest": params["expected_section_digest"]})
        .status_code
        == 422
    )
    assert (
        exact["client"]
        .get(path, params={**params, "expected_snapshot_digest": "0" * 64})
        .status_code
        == 412
    )
    section = exact["input_body"]["target_section"]["section_id"]
    assert exact["client"].get(path.replace(section, uid()), params=params).status_code == 404


def test_snapshot_head_changed_retains_original_nodes_but_blocks_new_save(exact):
    w = exact
    old = read_nodes(w)
    target = w["input_body"]["target_section"]
    changed = deepcopy(old["section_content"])
    changed["content"][0]["content"] = [{"type": "text", "text": "明确保存的新正文"}]
    response = w["client"].patch(
        f"/api/v1/bids/{w['bid']}/drafts/{target['draft_id']}",
        json={
            "base_draft_revision": target["base_draft_revision"],
            "changes": [
                {
                    "section_id": target["section_id"],
                    "base_section_revision": target["base_section_revision"],
                    "schema_digest": target["schema_digest"],
                    "content": changed,
                }
            ],
        },
        headers=headers(w, etag=etag("draft", target["draft_id"], target["base_draft_revision"])),
    )
    assert response.status_code == 200, response.text
    current = read_nodes(w)
    assert current["target"] == old["target"] and current["nodes"] == old["nodes"]
    assert set(current["blocking_reasons"]) == {
        "AUTHORING_PACKAGE_DRAFT_CHANGED",
        "AUTHORING_PACKAGE_SECTION_CHANGED",
    }
    assert save(w).status_code == 409


def test_head_change_preserves_selected_old_set_and_its_items(exact):
    w = exact
    first = read_facts(w).json()
    mutate_authority(w, "facts")
    later = read_facts(w)
    assert later.status_code == 200, later.text
    value = later.json()
    assert value["selection"] == first["selection"] and value["items"] == first["items"]
    assert (
        not value["head_matches"]
        and value["current_head"]["fact_set_id"] != value["selection"]["fact_set_id"]
    )
    assert "AUTHORING_PACKAGE_FACT_HEAD_CHANGED" in value["blocking_reasons"]
    assert save(w).status_code == 409


@pytest.mark.parametrize("change", ["source", "closed", "missing_basis", "official_source"])
def test_proof_lifecycle_and_prebid_boundary_are_observations_not_qualification(exact, change):
    w = exact
    if change in {"source", "closed"}:
        mutate_authority(w, change)
    elif change == "missing_basis":
        selected = w["input_body"]["facts"]["identity_fact_ids"][0]
        with connection() as c:
            lock_bid(c, w["bid"])
            append_decision(
                c,
                w["bid"],
                w["actor"],
                "fact",
                selected,
                {
                    "decision": "confirmed",
                    "reason": "Explicit missing synthetic basis",
                    "evidence_ids": [w["body_evidence"]],
                },
                basis=None,
            )
    else:
        from packages.rag.indexing import original_source_id

        # Append a prohibited ancestor; immutable existing sources stay untouched.
        with connection() as c:
            label = uid()
            c.execute(
                "INSERT INTO retrieval.source_nodes(id,kind,policy_class,known_at,digest) VALUES(%s,'label','official_label',clock_timestamp()-interval '1 day',%s)",
                (label, "a" * 64),
            )
            c.execute(
                "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',clock_timestamp()-interval '1 day')",
                (label,),
            )
            c.execute(
                "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
                (original_source_id(UUID(w["member"].document_version_id)), label),
            )
    response = read_facts(w)
    assert response.status_code == 200, response.text
    value = response.json()
    if change == "closed":
        assert "PROJECT_WORK_CLOSED" in value["blocking_reasons"]
    else:
        assert any(item["provenance_status"] == "unproven" for item in value["items"])
        reason = (
            "FACT_DECISION_BASIS_UNPROVEN"
            if change == "missing_basis"
            else "FACT_SOURCE_NOT_EFFECTIVE"
        )
        assert any(reason in item["blocking_reasons"] for item in value["items"])
    assert not value["admission_granted"] and not value["formal_decisions_allowed"]
    assert save(w).status_code == 409


def test_fact_page_change_rejected_before_continuation_and_new_parse_not_substituted(exact):
    w = exact
    first = read_facts(w, limit=1)
    assert first.status_code == 200 and first.json()["has_more"]
    add_new_parse(w)
    second = read_facts(w, limit=1, cursor=first.json()["next_cursor"])
    assert second.status_code == 200, second.text
    assert second.json()["observation_digest"] == first.json()["observation_digest"]
    mutate_authority(w, "source")
    changed = read_facts(w, limit=1, cursor=first.json()["next_cursor"])
    assert changed.status_code == 409 and changed.json()["code"].endswith("OBSERVATION_CHANGED")


def test_fact_set_page_change_and_cross_scope_cursor_rejected(exact):
    w = exact
    base = paths(w)[0] + "/fact-sets"
    first = w["client"].get(base, params={"limit": 1})
    assert first.status_code == 200 and first.json()["has_more"]
    cursor = first.json()["next_cursor"]
    assert read_facts(w, cursor=cursor).status_code == 422
    mutate_authority(w, "facts")
    changed = w["client"].get(base, params={"limit": 1, "cursor": cursor})
    assert changed.status_code == 409 and changed.json()["code"].endswith("OBSERVATION_CHANGED")


def test_single_rr_observation_survives_concurrent_committed_head_change(exact):
    w = exact
    with service.snapshot("sets") as c:
        before, items = facts.sets(c, w["bid"])
        mutate_authority(w, "facts")
        after, again = facts.sets(c, w["bid"])
        assert before == after and items == again
    with service.snapshot("sets") as c:
        fresh, _ = facts.sets(c, w["bid"])
    assert fresh["current_head"] != before["current_head"]


def test_actual_http_authenticated_unique_routes_and_unmodified_capture_bundle(exact):
    w = exact
    app = w["app"]
    for path in contract.ROOTS:
        assert sum(getattr(route, "path", None) == path for route in app.routes) == 1
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", trust_env=False
        ) as client:
            base, node_path = paths(w)
            assert client.get(base + "/fact-sets").status_code == 401
            client.cookies.set("session", w["client"].cookies.get("session"))
            response_specs = [
                ("capabilities", "/api/v1/authoring/package-input-capabilities", {}),
                ("nodes", node_path, node_params(w)),
                ("sets", base + "/fact-sets", {}),
                (
                    "facts",
                    base + f"/fact-sets/{w['input_body']['facts']['fact_set_id']}/facts",
                    fact_params(w),
                ),
                (
                    "snapshot_choices",
                    f"/api/v1/bids/{w['bid']}/work-contexts/choices",
                    {"kind": "draft_snapshot"},
                ),
            ]
            for role in ("target", "authority"):
                chosen = w["input_body"]["package_context"][role]
                package_path = f"/api/v1/bids/{w['bid']}/packages/{chosen['package_id']}/revisions"
                response_specs.extend(
                    [
                        (
                            role + "_heads",
                            f"/api/v1/bids/{w['bid']}/packages",
                            {"kind": "bid" if role == "target" else "authority"},
                        ),
                        (role + "_revisions", package_path, {}),
                        (role, package_path + "/" + chosen["revision_id"], {}),
                    ]
                )
            selected_target = w["input_body"]["package_context"]["target"]
            inventory_base = f"/api/v1/bids/{w['bid']}/packages/{selected_target['package_id']}/revisions/{selected_target['revision_id']}/requirement-inventories"
            response_specs.extend(
                [
                    ("inventories", inventory_base, {}),
                    (
                        "inventory",
                        inventory_base
                        + "/"
                        + w["input_body"]["package_context"]["inventory"]["id"],
                        {},
                    ),
                    (
                        "snapshot",
                        f"/api/v1/bids/{w['bid']}/work-contexts/draft_snapshot/{w['input_body']['target_section']['snapshot_id']}",
                        {},
                    ),
                ]
            )
            responses = []
            for name, path, params in response_specs:
                reply = client.get(path, params=params)
                assert reply.status_code == 200, reply.text
                responses.append(
                    {
                        "name": name,
                        "path": path,
                        "query": params,
                        "status": reply.status_code,
                        "etag": reply.headers.get("ETag"),
                        "body": reply.json(),
                    }
                )
            captured = client.post(w["input_base"], json=w["input_body"], headers=headers(w))
            assert captured.status_code == 201, captured.text
            responses.append(
                {
                    "name": "saved",
                    "path": w["input_base"],
                    "query": {},
                    "status": 201,
                    "body": captured.json(),
                }
            )
            w["database"]["owner"].execute(
                "UPDATE design.members SET active=false WHERE id=%s", (w["actor"],)
            )
            assert client.get(base + "/fact-sets").status_code == 401
            bundle = os.environ.get("FUSION_AUTHORING_CATALOG_BUNDLE")
            if bundle:
                destination = Path(bundle)
                assert not destination.exists()
                destination.write_text(
                    json.dumps(
                        {
                            "protocol": "authoring-input-catalog-native-http/1",
                            "synthetic_upstream": True,
                            "bid_id": w["bid"],
                            "request": w["input_body"],
                            "responses": responses,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive()
