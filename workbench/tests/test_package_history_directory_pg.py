"""Metadata discovery on real independent roles; no labels or qualification RPCs."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import test_package_history_pg as native
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from apps.api.package_historical_directory import router
from deploy.schema_plan import BASE_SQL
from packages.contracts import package_history_directory_api as contract
from packages.domain.runtime import Command, connection
from packages.model_governance import package_history_cpu as cpu

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "deploy/sql/package-history-directory.sql"
BASE = "/api/v1/package-historical-research"
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_HISTORY_DIRECTORY_PG") != "1",
    reason="fresh isolated metadata directory database required",
)


@pytest.fixture(scope="module")
def database():
    stream = native.database.__wrapped__()
    value = next(stream)
    try:
        value["owner"].execute(SQL.read_text())
        yield value
    finally:
        try:
            next(stream)
        except StopIteration:
            pass


@pytest.fixture
def api(database):
    stream = native.api.__wrapped__(database)
    value = next(stream)
    app = value["app"]
    previous = list(app.router.routes)
    app.include_router(router)
    try:
        yield value
    finally:
        app.router.routes[:] = previous
        try:
            next(stream)
        except StopIteration:
            pass


def checked(response, kind):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"].replace(" ", "") == "private,no-store"
    assert response.headers["vary"] == "Cookie"
    value = contract.validate(kind, response.json())
    assert not value["currentness_rechecked"] and not value["qualification_granted"]
    assert value["research_only"] and value["formal_eligibility"] == "unavailable"
    return value


def protocol(api, seed):
    document = cpu.protocol(seed=seed, bootstrap_iterations=100)
    with connection() as c:
        cmd = Command(
            c,
            api["actor"],
            "package-history-protocol",
            api["actor"],
            str(uuid4()),
            {"document": document},
        )
        result = c.execute(
            "SELECT package_historical_research.register_protocol(%s,%s,%s) AS value",
            (Jsonb(document), api["actor"], cmd.id),
        ).fetchone()["value"]
        cmd.finish(result, 201)
        return result


def counts(owner):
    return owner.execute(
        "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.audit_entries) AS audit,(SELECT count(*) FROM package_historical_research.exposures) AS exposures,(SELECT count(*) FROM package_historical_research.jobs) AS jobs,(SELECT count(*) FROM package_historical_research.results) AS results"
    ).fetchone()


def test_actual_directories_preserve_exact_native_metadata_without_business_writes(api, tmp_path):
    cases, pr, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    client = api["client"]
    before = counts(api["database"]["owner"])
    admissions = checked(
        client.get(
            BASE + "/admissions",
            params={"bid_id": w["scope"].bid_id, "scope_id": w["saved"]["manifest"]["id"]},
        ),
        "admissions",
    )
    assert admissions["total"] == 1 and admissions["items"][0]["id"] == w["admission"]["id"]
    assert admissions["items"][0]["digest"] == w["admission"]["digest"]
    assert admissions["items"][0]["current_status"] == "not_rechecked"
    assert "official_technical_value" not in admissions["items"][0]
    protocols = checked(client.get(BASE + "/protocols"), "protocols")
    chosen = next(item for item in protocols["items"] if item["id"] == pr["id"])
    assert chosen["document"] == pr["document"] and chosen["digest"] == pr["digest"]
    cohorts = checked(client.get(BASE + "/cohorts", params={"protocol_id": pr["id"]}), "cohorts")
    chosen = next(item for item in cohorts["items"] if item["id"] == cohort["id"])
    assert chosen["member_count"] == 5 and chosen["digest"] == cohort["digest"]
    jobs = checked(client.get(BASE + f"/cohorts/{cohort['id']}/jobs"), "jobs")
    assert jobs["total"] == 1 and jobs["items"][0]["id"] == task["job_id"]
    assert jobs["items"][0]["state"] == "queued" and not jobs["items"][0]["result_available"]
    assert jobs["items"][0]["result_digest"] is None
    assert counts(api["database"]["owner"]) == before
    with connection() as c:
        cmd = Command(
            c,
            w["actor"],
            "package-history-job-control",
            task["job_id"],
            str(uuid4()),
            {"action": "pause"},
        )
        changed = c.execute(
            "SELECT package_historical_research.control_job(%s,%s,'pause',%s,%s) AS value",
            (task["job_id"], task["generation"], w["actor"], cmd.id),
        ).fetchone()["value"]
        cmd.finish(changed, 200)
    observed = checked(client.get(BASE + f"/cohorts/{cohort['id']}/jobs"), "jobs")
    assert observed["items"][0]["state"] == "paused" and observed["items"][0]["generation"] == 2
    assert observed["observation_digest"] != jobs["observation_digest"]
    # Stored history remains discoverable after evidence ceases to authorize work.
    api["database"]["owner"].execute(
        "INSERT INTO package_historical_research.adapter_revocations(adapter_id,reason) VALUES(%s,'Synthetic source revocation')",
        (w["adapter_id"],),
    )
    stale = checked(
        client.get(BASE + "/admissions", params={"bid_id": w["scope"].bid_id}), "admissions"
    )
    assert stale["items"][0]["current_status"] == "not_rechecked"
    detail = client.get(BASE + "/admissions/" + w["admission"]["id"])
    assert detail.status_code == 200 and not detail.json()["current"]


def test_signed_keyset_pages_reject_changed_observations_and_cross_directory_replay(api):
    protocol(api, 1101)
    protocol(api, 1102)
    client = api["client"]
    first = checked(client.get(BASE + "/protocols?limit=1"), "protocols")
    assert first["has_more"] and first["next_cursor"]
    second = checked(
        client.get(BASE + "/protocols", params={"limit": 1, "cursor": first["next_cursor"]}),
        "protocols",
    )
    assert second["observation_digest"] == first["observation_digest"]
    assert second["items"][0]["id"] != first["items"][0]["id"]
    wrong = client.get(BASE + "/cohorts", params={"cursor": first["next_cursor"]})
    assert wrong.status_code == 422
    wrong = client.get(BASE + "/protocols", params={"cursor": first["next_cursor"] + "x"})
    assert wrong.status_code == 422
    protocol(api, 1103)
    changed = client.get(BASE + "/protocols", params={"cursor": first["next_cursor"]})
    assert changed.status_code == 409
    assert changed.json()["code"] == "PACKAGE_HISTORY_DIRECTORY_OBSERVATION_CHANGED"


def test_actual_repeatable_read_snapshot_and_independent_role_acl(api):
    pr = protocol(api, 2101)
    db = api["database"]
    with psycopg.connect(db["api_dsn"], row_factory=dict_row) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        before = c.execute(
            "SELECT package_historical_research.list_protocols(50,NULL,NULL) AS value"
        ).fetchone()["value"]
        protocol(api, 2102)
        after = c.execute(
            "SELECT package_historical_research.list_protocols(50,NULL,NULL) AS value"
        ).fetchone()["value"]
        assert before == after
        assert any(item["id"] == pr["id"] for item in before["items"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM package_historical_research.protocols")
    fresh = checked(api["client"].get(BASE + "/protocols"), "protocols")
    assert fresh["observation_digest"] != before["observation_digest"]
    for purpose in ("verify_dsn", "train_dsn", "evaluate_dsn", "worker_dsn"):
        with psycopg.connect(db[purpose]) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT package_historical_research.list_protocols(50,NULL,NULL)")
    with psycopg.connect(db["api_dsn"]) as c:
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="readonly_snapshot_required"
        ):
            c.execute("SELECT package_historical_research.list_protocols(50,NULL,NULL)")
    with psycopg.connect(db["api_dsn"], row_factory=dict_row) as c:
        acl = c.execute(
            "SELECT has_function_privilege(current_user,'package_historical_research.directory_page(text,jsonb,integer,uuid,design.sha256)','EXECUTE') AS helper,has_function_privilege(current_user,'package_historical_research.assert_directory_reader()','EXECUTE') AS guard"
        ).fetchone()
        assert not acl["helper"] and not acl["guard"]


def test_http_closed_filters_and_foreign_scopes_do_not_fall_back_to_global(api, tmp_path):
    case = native.independent_case(api, tmp_path)
    client = api["client"]
    for path in (
        "/admissions?limit=1&limit=1",
        "/admissions?latest=true",
        "/protocols?bid_id=" + str(uuid4()),
        "/cohorts?limit=51",
        "/admissions?scope_id=" + case["saved"]["manifest"]["id"],
    ):
        response = client.get(BASE + path)
        assert response.status_code == 422, (path, response.text)
    foreign = client.get(
        BASE + "/admissions",
        params={"bid_id": str(uuid4()), "scope_id": case["saved"]["manifest"]["id"]},
    )
    assert foreign.status_code == 404
    missing = client.get(BASE + f"/cohorts/{uuid4()}/jobs")
    assert missing.status_code == 404
    missing = client.get(BASE + "/cohorts", params={"protocol_id": str(uuid4())})
    assert missing.status_code == 404


def test_actual_base_only_http_reports_unavailable_and_unknown_totals(database):
    name = "fusion_history_directory_base_" + uuid4().hex[:8]
    admin_dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        try:
            with psycopg.connect(
                make_conninfo(admin_dsn, dbname=name), autocommit=True, row_factory=dict_row
            ) as owner:
                for path in BASE_SQL:
                    owner.execute((ROOT / path).read_text())
                base = database | {
                    "owner": owner,
                    "api_dsn": make_conninfo(database["api_dsn"], dbname=name),
                    "worker_dsn": make_conninfo(database["worker_dsn"], dbname=name),
                }
                with pytest.MonkeyPatch.context() as patch:
                    patch.setenv("API_DATABASE_DSN", base["api_dsn"])
                    stream = api.__wrapped__(base)
                    client = next(stream)
                    try:
                        for path, kind in (
                            ("/admissions", "admissions"),
                            ("/protocols", "protocols"),
                            ("/cohorts", "cohorts"),
                            (f"/cohorts/{uuid4()}/jobs", "jobs"),
                        ):
                            value = checked(client["client"].get(BASE + path), kind)
                            assert (
                                value["status"] == "unavailable" and not value["schema_configured"]
                            )
                            assert (
                                value["total"] is None
                                and value["has_more"] is None
                                and value["observation_digest"] is None
                            )
                            assert value["items"] == [] and not value["complete_observation"]
                    finally:
                        try:
                            next(stream)
                        except StopIteration:
                            pass
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(name)))
