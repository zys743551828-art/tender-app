"""Real nonowner ASGI requests against disposable full-BASE_SQL PostgreSQL."""
# ruff: noqa: F811

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_stable_lot_identity import (  # noqa: F401
    api,
    catalog,
    headers,
    post,
    uid,
    validate_response,
)

ADMIN_DSN = os.environ.get("FUSION_PACKAGE_API_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires explicit isolated package API PG17")


@pytest.fixture(scope="module")
def database():
    from deploy.bootstrap_fresh import BASE_SQL, ROOT

    plan = [(name, (ROOT / name).read_text(encoding="utf-8")) for name in BASE_SQL]
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_ENV_FILE", "explicit-test-no-business-profile")
        patch.setenv("APP_ORIGIN", "http://identity-v2.test")
        patch.setenv("SESSION_SECRET", uid())
        patch.setenv("CSRF_SECRET", uid())
        with psycopg.connect(ADMIN_DSN, autocommit=True, row_factory=dict_row) as admin:
            assert admin.info.dbname == "postgres"
            assert not admin.execute(
                "SELECT 1 FROM pg_database WHERE datname='fusion_package_api'"
            ).fetchone()
            assert not admin.execute(
                "SELECT 1 FROM pg_roles WHERE rolname='fusion_package_service_api'"
            ).fetchone()
            admin.execute("CREATE DATABASE fusion_package_api TEMPLATE template0")
            owner_dsn = make_conninfo(ADMIN_DSN, dbname="fusion_package_api")
            try:
                with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
                    assert owner.info.dbname == "fusion_package_api"
                    for _, source in plan:
                        owner.execute(source)
                    admin.execute(
                        "CREATE ROLE fusion_package_service_api LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    )
                    admin.execute("GRANT tender_api TO fusion_package_service_api")
                    api_dsn = make_conninfo(owner_dsn, user="fusion_package_service_api")
                    patch.setenv("API_DATABASE_DSN", api_dsn)
                    yield {"owner": owner, "api_dsn": api_dsn}
                    owner.execute("DROP OWNED BY fusion_package_service_api")
            finally:
                admin.execute("DROP DATABASE fusion_package_api WITH (FORCE)")
                admin.execute("DROP ROLE IF EXISTS fusion_package_service_api")


@pytest.fixture
def world(api):
    from test_bid_package_repository import add_document

    from packages.domain.bid_packages import BidScope

    project, lot, round_value, bidder = catalog(api)
    bid = post(
        api,
        "/bids",
        {
            "title": "synthetic package bid",
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    ).json()
    scope = BidScope(project["id"], lot["id"], round_value["id"], bid["id"], bidder["id"])
    c = api["database"]["owner"]
    with c.transaction():
        c.execute("SET LOCAL search_path TO design,public")
        member = add_document(c, scope, api["actor"])
        attach(c, scope.bid_id, api["actor"], member)
    item = {
        "member_id": "original",
        "document_version_id": member.document_version_id,
        "parse_run_id": member.parse.parse_run_id,
        "purposes": ["technical"],
        "parts": [
            {
                "part_id": "tech",
                "category": "technical",
                "first_page": 1,
                "last_page": 2,
                "shared_attachment": False,
                "heading_path": list(range(1, 12)),
            }
        ],
    }
    return {
        **api,
        "scope": scope,
        "member": member,
        "item": item,
        "base": f"/api/v1/bids/{bid['id']}/packages",
    }


def attach(c, bid, actor, member, role="body", *, verified=True):
    file, batch, upload = uid(), uid(), uid()
    c.execute(
        "INSERT INTO design.document_files(id,bid_id,role,revision,head_version_id) VALUES(%s,%s,%s,1,%s)",
        (file, bid, role, member.document_version_id),
    )
    c.execute(
        "INSERT INTO design.document_file_versions(bid_id,file_id,version_id,revision) VALUES(%s,%s,%s,1)",
        (bid, file, member.document_version_id),
    )
    c.execute(
        "INSERT INTO design.upload_batches(id,bid_id,revision,state,created_by) VALUES(%s,%s,1,'committed',%s)",
        (batch, bid, actor),
    )
    c.execute(
        """INSERT INTO design.uploads(id,bid_id,batch_id,filename,role,declared_digest,declared_size,staging_key,state,expires_at,verified_version_id,verified_retain_until)
    VALUES(%s,%s,%s,'synthetic.pdf',%s,%s,10,%s,%s,now()+interval '1 day',%s,now()+interval '1 day')""",
        (
            upload,
            bid,
            batch,
            role,
            member.file_digest,
            "synthetic/" + upload,
            "verified" if verified else "quarantined",
            member.document_version_id,
        ),
    )


def create(world, *, body=None, key=None):
    return world["client"].post(
        world["base"],
        json=body or {"kind": "bid", "members": [world["item"]]},
        headers=headers(world, key=key),
    )


def created(world):
    r = create(world)
    assert r.status_code == 201, r.text
    validate_response(world, "/api/v1/bids/{bid_id}/packages", "post", r)
    return r


def test_create_current_history_and_canonical_manifest(world):
    r = created(world)
    value = r.json()
    assert value["storage_eligible"] and not value["review_ready"]
    assert value["manifest"]["scope"]["lot_id"] == world["scope"].lot_id
    assert value["manifest"]["members"][0]["file_digest"] == world["member"].file_digest
    manifest = value["manifest"]
    path = world["base"] + "/" + manifest["package_id"]
    current = world["client"].get(path)
    assert current.json() == value and current.headers["etag"] == r.headers["etag"]
    history = path + "/revisions/" + manifest["revision_id"]
    assert world["client"].get(history).json() == value
    raw = world["client"].get(history + "/manifest")
    assert raw.status_code == 200
    assert (
        hashlib.sha256(raw.content).hexdigest()
        == value["digest"]
        == raw.headers["x-manifest-sha256"]
    )
    assert raw.json() == manifest
    assert "no-store" in raw.headers["cache-control"]


def test_append_cas_idempotency_and_old_bytes(world):
    first = created(world)
    old = first.json()["manifest"]
    path = world["base"] + "/" + old["package_id"]
    raw_url = path + "/revisions/" + old["revision_id"] + "/manifest"
    raw = world["client"].get(raw_url).content
    body = {"members": [world["item"]]}
    key = uid()
    h = headers(world, key=key, etag=first.headers["etag"])
    r = world["client"].post(path + "/revisions", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["manifest"]["revision"] == 2
    assert r.json()["manifest"]["predecessor_digest"] == first.json()["digest"]
    replay = world["client"].post(path + "/revisions", json=body, headers=h)
    assert replay.json() == r.json() and replay.headers["idempotent-replayed"] == "true"
    stale = world["client"].post(
        path + "/revisions", json=body, headers=headers(world, etag=first.headers["etag"])
    )
    assert stale.status_code == 412
    missing = world["client"].post(path + "/revisions", json=body, headers=headers(world))
    assert missing.status_code == 428
    assert world["client"].get(raw_url).content == raw
    assert world["client"].get(path).json()["digest"] == r.json()["digest"]


def test_create_replay_conflict_and_rollback(world):
    key = uid()
    r = create(world, key=key)
    assert r.status_code == 201
    assert create(world, key=key).json() == r.json()
    changed = {"kind": "authority", "members": [world["item"]]}
    assert create(world, body=changed, key=key).status_code == 409
    badkey = uid()
    assert create(world, body=changed, key=badkey).status_code == 422
    # Failed transaction includes Command; same key can retry corrected valid body.
    assert create(world, key=badkey).status_code == 201


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", {}),
        ("file_digest", "f" * 64),
        ("source_kind", "authority"),
        ("page_count", 2),
        ("parse", {}),
    ],
)
def test_client_cannot_inject_server_identity(world, field, value):
    item = {**world["item"], field: value}
    assert create(world, body={"kind": "bid", "members": [item]}).status_code == 422


def test_unfrozen_original_keeps_unknown_without_guessing_latest_run(world):
    item = {k: v for k, v in world["item"].items() if k != "parse_run_id"} | {"parts": []}
    r = create(world, body={"kind": "bid", "members": [item]})
    assert r.status_code == 201, r.text
    m = r.json()["manifest"]["members"][0]
    assert m["page_count"] is None and m["parse"]["status"] == "not_frozen"
    assert not r.json()["storage_eligible"] and not r.json()["review_ready"]
    assert (
        create(
            world, body={"kind": "bid", "members": [item | {"parts": world["item"]["parts"]}]}
        ).status_code
        == 422
    )


def test_wrong_parse_scope_failed_run_and_cross_bid_history(world):
    item = world["item"] | {"parse_run_id": uid()}
    assert create(world, body={"kind": "bid", "members": [item]}).status_code == 422
    owner = world["database"]["owner"]
    run = uid()
    owner.execute(
        "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,0,'failed','[]')",
        (run, world["scope"].bid_id, world["member"].document_version_id, "a" * 64, "b" * 64),
    )
    assert (
        create(
            world, body={"kind": "bid", "members": [world["item"] | {"parse_run_id": run}]}
        ).status_code
        == 422
    )
    r = created(world).json()["manifest"]
    wrong = f"/api/v1/bids/{uid()}/packages/{r['package_id']}/revisions/{r['revision_id']}"
    assert world["client"].get(wrong).status_code == 404
    wrongpkg = world["base"] + f"/{uid()}/revisions/{r['revision_id']}"
    assert world["client"].get(wrongpkg).status_code == 404


def test_auth_origin_csrf_and_required_idempotency(world):
    body = {"kind": "bid", "members": [world["item"]]}
    for field, value in [("Origin", "https://invalid.test"), ("X-CSRF-Token", "wrong")]:
        assert (
            world["client"]
            .post(world["base"], json=body, headers=headers(world) | {field: value})
            .status_code
            == 403
        )
    h = headers(world)
    del h["Idempotency-Key"]
    assert world["client"].post(world["base"], json=body, headers=h).status_code == 428
    world["client"].cookies.clear()
    assert world["client"].get(world["base"] + "/" + uid()).status_code == 401
    assert create(world).status_code == 401


def test_parallel_append_has_one_winner(world):
    first = created(world)
    path = world["base"] + "/" + first.json()["manifest"]["package_id"] + "/revisions"

    def append(_):
        return (
            world["client"]
            .post(
                path,
                json={"members": [world["item"]]},
                headers=headers(world, etag=first.headers["etag"]),
            )
            .status_code
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, range(2))) == [201, 412]


@pytest.mark.parametrize("state", ["closed", "terminated", "archived"])
def test_closed_work_rejects_new_packages_and_revisions_but_keeps_ack_history(world, state):
    key = uid()
    first = create(world, key=key)
    assert first.status_code == 201
    path = world["base"] + "/" + first.json()["manifest"]["package_id"]
    c = world["database"]["owner"]
    if state == "archived":
        c.execute(
            "UPDATE design.bid_profiles SET archived_at=now() WHERE bid_id=%s",
            (world["scope"].bid_id,),
        )
    else:
        c.execute(
            "UPDATE design.bid_profiles SET phase=%s WHERE bid_id=%s",
            (state, world["scope"].bid_id),
        )
    assert create(world).json()["code"] == "PROJECT_WORK_CLOSED"
    r = world["client"].post(
        path + "/revisions",
        json={"members": [world["item"]]},
        headers=headers(world, etag=first.headers["etag"]),
    )
    assert r.status_code == 409 and r.json()["code"] == "PROJECT_WORK_CLOSED"
    assert create(world, key=key).json() == first.json()
    assert world["client"].get(path).json() == first.json()
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.bid_package_revisions r JOIN design.bid_packages p ON p.id=r.package_id WHERE p.bid_id=%s",
            (world["scope"].bid_id,),
        ).fetchone()["n"]
        == 1
    )


def test_rebinding_requires_new_package_and_preserves_old_identity_bytes(world):
    first = created(world)
    manifest = first.json()["manifest"]
    path = world["base"] + "/" + manifest["package_id"]
    raw_url = path + "/revisions/" + manifest["revision_id"] + "/manifest"
    raw = world["client"].get(raw_url).content
    bidder = post(
        world, "/identity/bidders", {"name": "different subject", "reason": "explicit correction"}
    ).json()["bidder"]
    identity_url = f"/api/v1/bids/{world['scope'].bid_id}/identity"
    tag = world["client"].get(identity_url).headers["etag"]
    correction = world["client"].put(
        identity_url,
        json={"bidder_id": bidder["id"], "reason": "explicit correction"},
        headers=headers(world, etag=tag),
    )
    assert correction.status_code == 200, correction.text
    assert world["client"].get(path).json() == first.json()
    assert world["client"].get(raw_url).content == raw
    r = world["client"].post(
        path + "/revisions",
        json={"members": [world["item"]]},
        headers=headers(world, etag=first.headers["etag"]),
    )
    assert r.status_code == 409 and r.json()["code"] == "PACKAGE_PROFILE_SCOPE_MISMATCH"
    new = created(world).json()
    assert new["identity"]["bidder_id"] == bidder["id"]
    assert new["manifest"]["package_id"] != manifest["package_id"]


@pytest.mark.parametrize(
    "role,accepted",
    [
        ("tender", True),
        ("supplement", True),
        ("drawing", True),
        ("boq", True),
        ("body", False),
        ("official_result", False),
        ("other", False),
    ],
)
def test_authority_roles_require_server_verified_originals(world, role, accepted):
    from dataclasses import replace

    c = world["database"]["owner"]
    version = uid()
    with c.transaction():
        c.execute(
            "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) SELECT %s,bid_id,blob_id,'synthetic-authority.pdf',now(),'source_original',created_by FROM design.document_versions WHERE id=%s",
            (version, world["member"].document_version_id),
        )
        attach(
            c,
            world["scope"].bid_id,
            world["actor"],
            replace(world["member"], document_version_id=version),
            role,
        )
    item = {
        "member_id": "authority-original",
        "document_version_id": version,
        "purposes": ["requirements"],
        "parts": [],
    }
    r = create(world, body={"kind": "authority", "members": [item]})
    assert r.status_code == (201 if accepted else 422), r.text
    if accepted:
        assert r.json()["manifest"]["members"][0]["source_kind"] == "authority"
        assert not r.json()["storage_eligible"]


@pytest.mark.parametrize("classification", ["official_label", "post_outcome", "derived_mixed"])
def test_original_with_prohibited_known_source_cannot_enter_package(world, classification):
    world["database"]["owner"].execute(
        "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'document',%s,now(),%s)",
        (uid(), world["member"].document_version_id, classification, world["member"].file_digest),
    )
    r = create(world)
    assert r.status_code == 422 and r.json()["code"] == "PACKAGE_SOURCE_POLICY_REJECTED"


def test_unverified_or_uncommitted_document_and_cross_bid_member_rejected(world):
    from test_bid_package_repository import add_document

    c = world["database"]["owner"]
    with c.transaction():
        member = add_document(c, world["scope"], world["actor"])
    item = world["item"] | {
        "document_version_id": member.document_version_id,
        "parse_run_id": member.parse.parse_run_id,
    }
    r = create(world, body={"kind": "bid", "members": [item]})
    assert r.status_code == 422 and r.json()["code"] == "PACKAGE_COMMITTED_DOCUMENT_REQUIRED"
    with c.transaction():
        attach(c, world["scope"].bid_id, world["actor"], member, verified=False)
    r = create(world, body={"kind": "bid", "members": [item]})
    assert r.status_code == 422 and r.json()["code"] == "PACKAGE_VERIFIED_UPLOAD_REQUIRED"
    assert (
        create(
            world, body={"kind": "bid", "members": [item | {"document_version_id": uid()}]}
        ).status_code
        == 422
    )


def test_historical_identity_schema_retains_v1_and_rejects_mixed_identity(world):
    from jsonschema import Draft202012Validator

    from packages.contracts.bid_package_api import SCHEMAS
    from packages.domain.review_identity import digest

    value = created(world).json()
    legacy = {
        k: v
        for k, v in value["identity"].items()
        if k not in {"identity_version", "lot_id", "digest"}
    }
    legacy["digest"] = digest(legacy)
    validator = Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS["BidPackageStoredView"]]}
    )
    assert validator.is_valid(value | {"identity": legacy})
    assert not validator.is_valid(value | {"identity": legacy | {"lot_id": world["scope"].lot_id}})
    assert not validator.is_valid(
        value | {"identity": legacy | {"identity_version": "bid-identity/2"}}
    )


def test_multiple_own_volumes_are_explicit_and_never_replace_current_body(world):
    from test_bid_package_repository import add_document

    c = world["database"]["owner"]
    with c.transaction():
        second = add_document(c, world["scope"], world["actor"], category="qualification")
        attach(c, world["scope"].bid_id, world["actor"], second)
    item = world["item"] | {
        "member_id": "qualification-original",
        "document_version_id": second.document_version_id,
        "parse_run_id": second.parse.parse_run_id,
        "purposes": ["qualification"],
        "parts": [
            {
                "part_id": "qualification",
                "category": "qualification",
                "first_page": 1,
                "last_page": 2,
                "shared_attachment": False,
                "heading_path": [],
            }
        ],
    }
    r = create(world, body={"kind": "bid", "members": [world["item"], item]})
    assert r.status_code == 201, r.text
    assert [m["document_version_id"] for m in r.json()["manifest"]["members"]] == [
        world["member"].document_version_id,
        second.document_version_id,
    ]
    assert (
        c.execute(
            "SELECT current_body_id FROM design.bid_profiles WHERE bid_id=%s",
            (world["scope"].bid_id,),
        ).fetchone()["current_body_id"]
        is None
    )


def test_explicit_new_parse_creates_new_revision_preserving_original_manifest(world):
    c = world["database"]["owner"]
    first = created(world)
    manifest = first.json()["manifest"]
    path = world["base"] + "/" + manifest["package_id"]
    raw_url = path + "/revisions/" + manifest["revision_id"] + "/manifest"
    raw = world["client"].get(raw_url).content
    oldrun, newrun = world["member"].parse.parse_run_id, uid()
    with c.transaction():
        c.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) SELECT %s,bid_id,document_version_id,parser_digest,%s,page_count,coverage,gaps FROM design.parse_runs WHERE id=%s",
            (newrun, "d" * 64, oldrun),
        )
        c.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,printed_label,width,height,rotation,quality,gaps) SELECT bid_id,%s,physical_page,printed_label,width,height,rotation,quality,gaps FROM design.pages WHERE parse_id=%s",
            (newrun, oldrun),
        )
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest) SELECT gen_random_uuid(),bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest FROM design.evidence_blocks WHERE parse_id=%s",
            (newrun, oldrun),
        )
    r = world["client"].post(
        path + "/revisions",
        json={"members": [world["item"] | {"parse_run_id": newrun}]},
        headers=headers(world, etag=first.headers["etag"]),
    )
    assert r.status_code == 201, r.text
    assert r.json()["digest"] != first.json()["digest"]
    assert r.json()["manifest"]["members"][0]["parse"]["parse_run_id"] == newrun
    assert world["client"].get(raw_url).content == raw


@pytest.mark.parametrize("field", ["member_id", "purposes", "part_id", "category", "heading_path"])
@pytest.mark.parametrize("invalid", ["bad\x00value", "bad\ud800value", "bad\udfffvalue"])
def test_invalid_text_is_422_before_commands_or_packages(world, field, invalid):
    from copy import deepcopy

    from jsonschema import Draft202012Validator

    from packages.contracts.bid_package_api import SCHEMAS

    item = deepcopy(world["item"])
    if field in {"part_id", "category"}:
        item["parts"][0][field] = invalid
    elif field == "heading_path":
        item["parts"][0][field] = [invalid]
    else:
        item[field] = [invalid] if field == "purposes" else invalid
    body = {"kind": "bid", "members": [item]}
    assert not Draft202012Validator(SCHEMAS["CreateBidPackage"]).is_valid(body)
    response = world["client"].post(
        world["base"],
        content=json.dumps(body, ensure_ascii=True),
        headers=headers(world) | {"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_REQUEST" and not response.json()["retryable"]
    c = world["database"]["owner"]
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.bid_packages WHERE bid_id=%s",
            (world["scope"].bid_id,),
        ).fetchone()["n"]
        == 0
    )
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.commands WHERE actor_id=%s AND command_kind IN ('create_bid_package','append_bid_package')",
            (world["actor"],),
        ).fetchone()["n"]
        == 0
    )


def test_valid_non_bmp_text_roundtrips_raw_json_and_append_rejects_invalid_text(world):
    from copy import deepcopy

    item = deepcopy(world["item"])
    for field in ("member_id", "purposes", "part_id", "category"):
        value = "中文😀-" + field
        if field in {"part_id", "category"}:
            item["parts"][0][field] = value
        else:
            item[field] = [value] if field == "purposes" else value
    body = {"kind": "bid", "members": [item]}
    response = world["client"].post(
        world["base"],
        content=json.dumps(body, ensure_ascii=True),
        headers=headers(world) | {"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text
    validate_response(world, "/api/v1/bids/{bid_id}/packages", "post", response)
    stored = response.json()["manifest"]
    assert stored["members"][0]["member_id"] == item["member_id"]
    assert stored["members"][0]["parts"][0]["category"] == item["parts"][0]["category"]
    path = world["base"] + "/" + stored["package_id"]
    raw = world["client"].get(path + "/revisions/" + stored["revision_id"] + "/manifest")
    assert hashlib.sha256(raw.content).hexdigest() == response.json()["digest"]
    item["purposes"] = ["bad\ud800value"]
    invalid = world["client"].post(
        path + "/revisions",
        content=json.dumps({"members": [item]}, ensure_ascii=True),
        headers=headers(world, etag=response.headers["etag"])
        | {"Content-Type": "application/json"},
    )
    assert invalid.status_code == 422 and not invalid.json()["retryable"]
    c = world["database"]["owner"]
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.bid_package_revisions WHERE package_id=%s",
            (stored["package_id"],),
        ).fetchone()["n"]
        == 1
    )
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.commands WHERE actor_id=%s AND command_kind='append_bid_package'",
            (world["actor"],),
        ).fetchone()["n"]
        == 0
    )


def test_graph_writer_wins_then_waiting_api_rechecks_new_label_ancestor(world):
    from packages.knowledge.sources import lock_graph

    database = world["database"]
    owner = database["owner"]
    # Writer only touches source graph; it never obtains the package API's bid lock.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(database["api_dsn"], row_factory=dict_row) as writer:
            lock_graph(writer)
            child, parent = uid(), uid()
            writer.execute(
                "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'document','prebid_content',now(),%s)",
                (child, world["member"].document_version_id, world["member"].file_digest),
            )
            writer.execute(
                "INSERT INTO retrieval.source_nodes(id,kind,policy_class,known_at,digest) VALUES(%s,'label','official_label',now(),%s)",
                (parent, "f" * 64),
            )
            writer.execute(
                "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
                (child, parent),
            )
            future = pool.submit(create, world)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    blocked = owner.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE usename='fusion_package_service_api' AND query LIKE '%%pg_advisory_xact_lock(90127,1)%%' AND cardinality(pg_blocking_pids(pid))>0"
                    ).fetchone()
                    if blocked:
                        break
                    Event().wait(0.02)
                else:
                    pytest.fail("Package API did not wait on actual source graph authority lock")
                assert not future.done()
                writer.commit()
                response = future.result(timeout=10)
                assert response.status_code == 422, response.text
                assert response.json()["code"] == "PACKAGE_SOURCE_POLICY_REJECTED"
            finally:
                writer.rollback()
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.bid_packages WHERE bid_id=%s",
            (world["scope"].bid_id,),
        ).fetchone()["n"]
        == 0
    )

    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.commands WHERE actor_id=%s AND command_kind='create_bid_package'",
            (world["actor"],),
        ).fetchone()["n"]
        == 0
    )


def test_package_and_history_discovery_scoped_signed_pages(world):
    values = [created(world) for _ in range(3)]
    response = world["client"].get(world["base"] + "?kind=bid&limit=1")
    assert response.status_code == 200
    validate_response(world, "/api/v1/bids/{bid_id}/packages", "get", response)
    first = response.json()
    assert first["has_more"] and first["next_cursor"]
    second = world["client"].get(
        world["base"], params={"kind": "bid", "limit": 2, "cursor": first["next_cursor"]}
    )
    assert len(second.json()["items"]) == 2 and not second.json()["has_more"]
    assert len({p["id"] for p in first["items"] + second.json()["items"]}) == 3
    assert world["client"].get(world["base"] + "?kind=authority").json()["items"] == []
    for params in (
        {"kind": "authority", "cursor": first["next_cursor"]},
        {"kind": "bid", "cursor": first["next_cursor"] + "x"},
        {"limit": 0},
    ):
        assert world["client"].get(world["base"], params=params).status_code == 422
    otherbid = post(world, "/bids", {"title": "other discovery bid"}).json()["id"]
    assert (
        world["client"]
        .get(
            f"/api/v1/bids/{otherbid}/packages",
            params={"kind": "bid", "cursor": first["next_cursor"]},
        )
        .status_code
        == 422
    )
    package = values[0].json()["manifest"]["package_id"]
    path = world["base"] + "/" + package + "/revisions"
    append = world["client"].post(
        path,
        json={"members": [world["item"]]},
        headers=headers(world, etag=values[0].headers["etag"]),
    )
    assert append.status_code == 201
    page = world["client"].get(path + "?limit=1")
    validate_response(world, "/api/v1/bids/{bid_id}/packages/{package_id}/revisions", "get", page)
    assert page.json()["items"][0]["revision"] == 2 and page.json()["has_more"]
    older = world["client"].get(path, params={"cursor": page.json()["next_cursor"]})
    assert [r["revision"] for r in older.json()["items"]] == [1]
    assert (
        world["client"]
        .get(
            world["base"] + "/" + values[1].json()["manifest"]["package_id"] + "/revisions",
            params={"cursor": page.json()["next_cursor"]},
        )
        .status_code
        == 422
    )


def test_discovery_enumerates_committed_versions_and_exact_parse_runs_without_choosing_latest(
    world,
):
    from test_bid_package_repository import add_document

    c = world["database"]["owner"]
    with c.transaction():
        second = add_document(c, world["scope"], world["actor"])
        attach(c, world["scope"].bid_id, world["actor"], second, verified=False)
    docpath = f"/api/v1/bids/{world['scope'].bid_id}/package-documents"
    docs = world["client"].get(docpath + "?kind=bid&limit=1")
    validate_response(world, "/api/v1/bids/{bid_id}/package-documents", "get", docs)
    more = world["client"].get(
        docpath, params={"kind": "bid", "cursor": docs.json()["next_cursor"]}
    )
    all_docs = docs.json()["items"] + more.json()["items"]
    assert {d["id"] for d in all_docs} == {
        second.document_version_id,
        world["member"].document_version_id,
    }
    assert {d["id"]: d["verified_upload"] for d in all_docs}[second.document_version_id] is False
    assert (
        world["client"]
        .get(docpath, params={"kind": "authority", "cursor": docs.json()["next_cursor"]})
        .status_code
        == 422
    )
    for coverage in ("partial", "failed"):
        c.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,0,%s,'[]')",
            (
                uid(),
                world["scope"].bid_id,
                world["member"].document_version_id,
                "a" * 64,
                "b" * 64,
                coverage,
            ),
        )
    parsepath = docpath + "/" + world["member"].document_version_id + "/parses"
    parses = world["client"].get(parsepath + "?limit=1")
    validate_response(
        world, "/api/v1/bids/{bid_id}/package-documents/{document_version_id}/parses", "get", parses
    )
    remaining = world["client"].get(parsepath, params={"cursor": parses.json()["next_cursor"]})
    assert {p["coverage"] for p in parses.json()["items"] + remaining.json()["items"]} == {
        "complete",
        "partial",
        "failed",
    }
    assert (
        world["client"]
        .get(
            docpath + "/" + second.document_version_id + "/parses",
            params={"cursor": parses.json()["next_cursor"]},
        )
        .status_code
        == 422
    )
    assert world["client"].get(docpath + "/" + uid() + "/parses").status_code == 404
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.bid_packages WHERE bid_id=%s",
            (world["scope"].bid_id,),
        ).fetchone()["n"]
        == 0
    )
    world["client"].cookies.clear()
    for path in (world["base"], docpath, parsepath):
        assert world["client"].get(path).status_code == 401
