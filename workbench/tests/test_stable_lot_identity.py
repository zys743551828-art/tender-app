"""Real API LOGIN/ASGI and SQL identity-v2 guards in a disposable dedicated DB."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ADMIN_DSN = os.environ.get("FUSION_IDENTITY_TEST_ADMIN_DSN")
pytestmark = pytest.mark.skipif(
    not ADMIN_DSN, reason="requires explicit local disposable PG17 admin"
)


def uid():
    return str(uuid4())


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
            assert admin.execute("SELECT current_database() AS n").fetchone()["n"] == "postgres"
            assert (
                admin.execute(
                    "SELECT 1 FROM pg_database WHERE datname='fusion_identity_api'"
                ).fetchone()
                is None
            )
            assert (
                admin.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname='fusion_identity_api'"
                ).fetchone()
                is None
            )
            admin.execute("CREATE DATABASE fusion_identity_api TEMPLATE template0")
            owner_dsn = make_conninfo(ADMIN_DSN, dbname="fusion_identity_api")
            try:
                with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
                    assert (
                        owner.execute("SELECT current_database() AS n").fetchone()["n"]
                        == "fusion_identity_api"
                    )
                    for _, source in plan:
                        owner.execute(source)
                    admin.execute(
                        "CREATE ROLE fusion_identity_api LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    )
                    admin.execute("GRANT tender_api TO fusion_identity_api")
                    api_dsn = make_conninfo(owner_dsn, user="fusion_identity_api")
                    patch.setenv("API_DATABASE_DSN", api_dsn)
                    yield {"owner": owner, "api_dsn": api_dsn}
                    owner.execute("DROP OWNED BY fusion_identity_api")
            finally:
                # Exact explicitly created test DB only; never attach to/rebuild a business DB.
                admin.execute("DROP DATABASE fusion_identity_api WITH (FORCE)")
                admin.execute("DROP ROLE IF EXISTS fusion_identity_api")


def api_connection(database):
    c = psycopg.connect(database["api_dsn"], row_factory=dict_row)
    c.execute("SET search_path TO design,public")
    return c


@pytest.fixture
def api(database):
    from fastapi.testclient import TestClient

    from apps.api.auth import password_hash
    from apps.api.main import app

    actor, login, password = uid(), "synthetic-" + uid(), uid()
    database["owner"].execute(
        "INSERT INTO design.members(id,display_name) VALUES(%s,'synthetic identity API actor')",
        (actor,),
    )
    database["owner"].execute(
        "INSERT INTO design.credentials(member_id,login_name,password_hash) VALUES(%s,%s,%s)",
        (actor, login, password_hash(password)),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"login_name": login, "password": password},
            headers={"Origin": "http://identity-v2.test"},
        )
        assert response.status_code == 200, response.json()
        yield {
            "client": client,
            "csrf": response.json()["csrf_token"],
            "actor": actor,
            "database": database,
            "app": app,
        }


def headers(api, *, key=None, etag=None):
    return {
        "Origin": "http://identity-v2.test",
        "X-CSRF-Token": api["csrf"],
        "Idempotency-Key": key or uid(),
    } | ({"If-Match": etag} if etag else {})


def post(api, path, body, key=None):
    response = api["client"].post("/api/v1" + path, json=body, headers=headers(api, key=key))
    assert response.status_code == 201, response.json()
    validate_response(api, "/api/v1" + path, "post", response)
    return response


def validate_response(api, path, method, response):
    from jsonschema import Draft202012Validator, FormatChecker

    actual = api["app"].openapi()
    schema = actual["paths"][path][method]["responses"][str(response.status_code)]["content"][
        "application/json"
    ]["schema"]
    Draft202012Validator(
        {"components": actual["components"], "allOf": [schema]}, format_checker=FormatChecker()
    ).validate(response.json())


def catalog(api):
    project = post(
        api,
        "/identity/engineering-projects",
        {"title": "synthetic project", "reason": "explicit project"},
    ).json()
    lot = post(
        api,
        "/identity/lots",
        {
            "engineering_project_id": project["id"],
            "label": "same visible lot",
            "reason": "explicit stable lot",
        },
    ).json()
    round_value = post(
        api,
        "/identity/rounds",
        {
            "engineering_project_id": project["id"],
            "lot_id": lot["id"],
            "round_no": 1,
            "reason": "explicit round",
        },
    ).json()
    bidder = post(
        api, "/identity/bidders", {"name": "synthetic bidder", "reason": "explicit actual bidder"}
    ).json()["bidder"]
    return project, lot, round_value, bidder


def test_actual_login_catalog_round_bid_and_storage_form_one_identity_v2_chain(api):
    from test_bid_package_repository import add_document

    from packages.domain.bid_package_repository import load_revision, save_revision
    from packages.domain.bid_packages import BidScope, PackageKind, PackageRevision

    project, lot, round_value, bidder = catalog(api)
    bid = post(
        api,
        "/bids",
        {
            "title": "synthetic bid",
            "engineering_project_id": project["id"],
            "lot_id": lot["id"],
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    ).json()
    identity = bid["identity"]
    assert identity["lot_id"] == lot["id"] and identity["identity_version"] == "bid-identity/2"
    assert identity["binding_status"] == "confirmed"
    with api_connection(api["database"]) as c:
        assert c.execute("SELECT current_user AS n").fetchone()["n"] == "fusion_identity_api"
        scope = BidScope(project["id"], lot["id"], round_value["id"], bid["id"], bidder["id"])
        member = add_document(c, scope, api["actor"])
        package = PackageRevision(uid(), uid(), 1, PackageKind.BID, scope, (member,))
        save_revision(c, package, expected_digest=None)
        assert load_revision(c, bid["id"], package.revision_id) == package
        bound = c.execute(
            "SELECT payload FROM design.audit_entries WHERE id=%s", (identity["authority_id"],)
        ).fetchone()["payload"]
        assert (
            bound["identity_version"] == "bid-identity/2" and bound["after"]["lot_id"] == lot["id"]
        )


def test_auth_origin_csrf_idempotency_and_schema_errors_are_real(api):
    client = api["client"]
    body = {"title": "scope", "reason": "explicit"}
    assert client.post("/api/v1/identity/engineering-projects", json=body).status_code == 403
    assert (
        client.post(
            "/api/v1/identity/engineering-projects",
            json=body,
            headers=headers(api) | {"X-CSRF-Token": "wrong"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/identity/engineering-projects",
            json=body,
            headers=headers(api) | {"Origin": "http://wrong.test"},
        ).status_code
        == 403
    )
    no_key = headers(api)
    del no_key["Idempotency-Key"]
    assert (
        client.post("/api/v1/identity/engineering-projects", json=body, headers=no_key).status_code
        == 428
    )
    key = uid()
    first = post(api, "/identity/engineering-projects", body, key)
    replay = post(api, "/identity/engineering-projects", body, key)
    assert replay.json() == first.json() and replay.headers["Idempotent-Replayed"] == "true"
    assert (
        client.post(
            "/api/v1/identity/engineering-projects",
            json=body | {"title": "changed"},
            headers=headers(api, key=key),
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/identity/lots",
            json={"engineering_project_id": "bad", "label": "", "reason": "x"},
            headers=headers(api),
        ).status_code
        == 422
    )
    client.cookies.clear()
    assert client.get("/api/v1/identity/engineering-projects").status_code == 401


def test_stable_lot_scope_uniqueness_and_cursor_are_not_display_name_matching(api):
    project, lot, round_value, _ = catalog(api)
    same_name = post(
        api,
        "/identity/lots",
        {
            "engineering_project_id": project["id"],
            "label": lot["label"],
            "reason": "distinct explicit lot",
        },
    ).json()
    assert same_name["id"] != lot["id"]
    post(
        api,
        "/identity/rounds",
        {
            "engineering_project_id": project["id"],
            "lot_id": same_name["id"],
            "round_no": 1,
            "reason": "other stable lot round",
        },
    )
    conflict = api["client"].post(
        "/api/v1/identity/rounds",
        json={
            "engineering_project_id": project["id"],
            "lot_id": lot["id"],
            "round_no": 1,
            "reason": "duplicate",
        },
        headers=headers(api),
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "ROUND_NUMBER_CONFLICT"
    listing = (
        api["client"]
        .get("/api/v1/identity/lots", params={"engineering_project_id": project["id"], "limit": 1})
        .json()
    )
    assert listing["has_more"]
    filtered = (
        api["client"]
        .get(
            "/api/v1/identity/rounds",
            params={"engineering_project_id": project["id"], "lot_id": lot["id"]},
        )
        .json()
    )
    assert [r["id"] for r in filtered["items"]] == [round_value["id"]]
    other = post(
        api, "/identity/engineering-projects", {"title": "other", "reason": "other engineering"}
    ).json()
    bad = api["client"].get(
        "/api/v1/identity/lots",
        params={"engineering_project_id": other["id"], "cursor": listing["next_cursor"]},
    )
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_CURSOR"
    mismatch = api["client"].post(
        "/api/v1/identity/rounds",
        json={"engineering_project_id": other["id"], "lot_id": lot["id"], "reason": "wrong scope"},
        headers=headers(api),
    )
    assert mismatch.status_code == 422


def test_unselected_lot_is_pending_and_explicit_correction_is_cas_guarded(api):
    project, lot, round_value, bidder = catalog(api)
    pending = post(
        api, "/bids", {"title": "without explicit lot", "bidder_id": bidder["id"]}
    ).json()
    assert (
        pending["identity"]["lot_id"] is None and pending["identity"]["binding_status"] == "pending"
    )
    endpoint = "/api/v1/bids/" + pending["id"] + "/identity"
    current = api["client"].get(endpoint)
    body = {"bidder_id": bidder["id"], "reason": "explicit confirmation"}
    denied = api["client"].put(
        endpoint, json=body, headers=headers(api, etag=current.headers["etag"])
    )
    assert denied.status_code == 409 and denied.json()["code"] == "STABLE_LOT_REQUIRED"
    body |= {"round_id": round_value["id"], "lot_id": lot["id"]}
    key = uid()
    corrected = api["client"].put(
        endpoint, json=body, headers=headers(api, key=key, etag=current.headers["etag"])
    )
    assert corrected.status_code == 200, corrected.json()
    assert corrected.json()["identity"]["binding_status"] == "confirmed"
    replay = api["client"].put(
        endpoint, json=body, headers=headers(api, key=key, etag=current.headers["etag"])
    )
    assert replay.status_code == 200 and replay.headers["Idempotent-Replayed"] == "true"
    stale = api["client"].put(
        endpoint,
        json=body | {"reason": "another change"},
        headers=headers(api, etag=current.headers["etag"]),
    )
    assert stale.status_code == 412


def test_legacy_binding_missing_stable_lot_is_not_reinterpreted_or_modified(api):
    from jsonschema import Draft202012Validator
    from test_bid_package_repository import seed

    from packages.identity import repository
    from packages.identity.contracts import HISTORICAL_SNAPSHOT, SNAPSHOT

    with api_connection(api["database"]) as c:
        world = seed(c)
        bid = world["scope"].bid_id
        frozen = repository.snapshot(c, bid)
        legacy = {k: v for k, v in frozen.items() if k not in {"lot_id", "identity_version"}}
        from packages.domain.review_identity import digest

        legacy["digest"] = digest({k: v for k, v in legacy.items() if k != "digest"})
        assert Draft202012Validator(HISTORICAL_SNAPSHOT).is_valid(legacy)
        assert not Draft202012Validator(SNAPSHOT).is_valid(legacy)
        legacy_after = {k: v for k, v in repository.association(c, bid).items() if k != "lot_id"}
        repository.record(
            c,
            api["actor"],
            bid,
            repository.BOUND,
            {
                "after": legacy_after,
                "before": None,
                "confirmed": True,
                "reason": "synthetic old unversioned record",
            },
            None,
        )
        row = c.execute(
            "SELECT id,payload FROM design.audit_entries WHERE bid_id=%s AND payload->>'reason'='synthetic old unversioned record'",
            (bid,),
        ).fetchone()
        original = row["payload"]
        assert repository.snapshot(c, bid)["binding_status"] == "pending"
        assert (
            c.execute(
                "SELECT payload FROM design.audit_entries WHERE id=%s", (row["id"],)
            ).fetchone()["payload"]
            == original
        )


def test_direct_sql_after_waiting_for_bid_lock_rechecks_new_profile_snapshot(api):
    from test_bid_package_repository import seed

    from packages.identity import repository

    database = api["database"]
    with api_connection(database) as creator:
        world = seed(creator)
        p = world["package"]
        old_identity = repository.snapshot(creator, p.scope.bid_id)
        new_lot, new_round = uid(), uid()
        creator.execute(
            "INSERT INTO design.engineering_lots VALUES(%s,%s,'lot A')",
            (new_lot, p.scope.engineering_project_id),
        )
        creator.execute(
            "INSERT INTO design.bid_rounds(id,engineering_project_id,lot,lot_id,round_no) VALUES(%s,%s,'lot A',%s,1)",
            (new_round, p.scope.engineering_project_id, new_lot),
        )
        creator.execute(
            "INSERT INTO design.bid_packages VALUES(%s,%s,'bid',%s,%s,%s,%s)",
            (
                p.package_id,
                p.scope.bid_id,
                p.scope.engineering_project_id,
                p.scope.lot_id,
                p.scope.round_id,
                p.scope.bidder_id,
            ),
        )
    started = Event()
    pid = []

    def insert_old_statement():
        with api_connection(database) as waiting:
            pid.append(waiting.execute("SELECT pg_backend_pid() AS p").fetchone()["p"])
            started.set()
            try:
                waiting.execute(
                    """INSERT INTO design.bid_package_revisions
                    (id,package_id,revision,predecessor_digest,digest,manifest,identity_authority_id,identity_digest,bidder_status,identity_snapshot)
                    VALUES(%s,%s,1,null,%s,%s,%s,%s,'confirmed',%s)""",
                    (
                        p.revision_id,
                        p.package_id,
                        p.manifest_digest,
                        Jsonb(p.manifest()),
                        old_identity["authority_id"],
                        old_identity["digest"],
                        Jsonb(old_identity),
                    ),
                )
            except psycopg.Error as error:
                waiting.rollback()
                return str(error)
            waiting.rollback()
            return "incorrectly accepted old snapshot"

    with api_connection(database) as updater, ThreadPoolExecutor(max_workers=1) as pool:
        updater.execute("SELECT id FROM design.bids WHERE id=%s FOR UPDATE", (p.scope.bid_id,))
        future = pool.submit(insert_old_statement)
        assert started.wait(5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            blocked = updater.execute(
                "SELECT cardinality(pg_blocking_pids(%s))>0 AS b", (pid[0],)
            ).fetchone()["b"]
            if blocked:
                break
            Event().wait(0.02)
        else:
            pytest.fail("INSERT did not wait on the actual bid lock")
        updater.execute(
            "UPDATE design.bid_profiles SET round_id=%s WHERE bid_id=%s",
            (new_round, p.scope.bid_id),
        )
        repository.record_binding(
            updater,
            p.scope.bid_id,
            world["actor"],
            None,
            reason="explicit other stable same-name lot",
            confirmed=True,
        )
        updater.commit()
        assert "package_current_profile_mismatch" in future.result(timeout=5)


@pytest.mark.parametrize(
    "scenario",
    [
        "test_same_company_reused_and_similar_names_stay_distinct",
        "test_no_default_is_silently_applied_to_project",
        "test_new_lot_and_new_round_do_not_reuse_work_units",
        "test_correction_preserves_audit_identity_at_time_and_does_not_invent_history",
        "test_delayed_transaction_default_follows_action_order_not_transaction_start",
        "test_delayed_correction_is_not_backdated_to_transaction_start",
        "test_login_http_registration_default_cas_and_bid_correction",
        "test_directory_pagination_discovers_more_than_100_and_binds_filters",
    ],
)
def test_existing_identity_pg_scenarios_with_explicit_v2_test_database(api, scenario):
    import test_identity

    from packages.domain.runtime import assert_role, connection
    from packages.domain.runtime import uid as uuid_value
    from packages.identity import repository

    assert_role()
    with connection() as c:
        actor = uuid_value()
        c.execute(
            "INSERT INTO members(id,display_name) VALUES(%s,'synthetic prior identity actor')",
            (actor,),
        )
        company = repository.register_bidder(
            c, actor, "prior synthetic bidder", "explicit registration", None
        )
        other = repository.register_bidder(
            c, actor, "prior synthetic other bidder", "explicit registration", None
        )
    # Reuse the original assertions in the actual limited LOGIN, not a replacement mock model.
    getattr(test_identity, scenario)({"actor": actor, "company": company, "other": other})


def test_automatic_round_limit_and_v2_confirmed_shape_are_explicit(api):
    from jsonschema import Draft202012Validator

    from packages.identity.contracts import HISTORICAL_SNAPSHOT, SNAPSHOT

    project, lot, round_value, bidder = catalog(api)
    post(
        api,
        "/identity/rounds",
        {
            "engineering_project_id": project["id"],
            "lot_id": lot["id"],
            "round_no": 2147483647,
            "reason": "synthetic storage boundary",
        },
    )
    response = api["client"].post(
        "/api/v1/bids",
        json={
            "title": "overflow round",
            "bidder_id": bidder["id"],
            "engineering_project_id": project["id"],
            "lot_id": lot["id"],
        },
        headers=headers(api),
    )
    assert response.status_code == 422 and response.json()["code"] == "ROUND_NUMBER_LIMIT"
    bid = post(
        api,
        "/bids",
        {
            "title": "explicit existing round",
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    ).json()
    identity = bid["identity"]
    assert Draft202012Validator(SNAPSHOT).is_valid(identity)
    invalid = identity | {"lot_id": None}
    assert not Draft202012Validator(SNAPSHOT).is_valid(invalid)
    assert not Draft202012Validator(HISTORICAL_SNAPSHOT).is_valid(invalid)
