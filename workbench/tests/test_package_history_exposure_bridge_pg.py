"""Optional cross-namespace guard on real independent LOGINs; synthetic facts only.

Legacy v1 records model pre-existing historical rows. They are initialized as
explicit fixtures, never manufactured by a production qualification endpoint.
The unchanged legacy SQL guard must pass before its bridge is installed.
"""
# ruff: noqa: F401,F811

import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import psycopg
import pytest
import test_package_history_pg as native
from package_history_legacy_fixtures import cohort as legacy_cohort
from package_history_legacy_fixtures import item as legacy_item
from package_history_legacy_fixtures import research_attempt
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_package_history_pg import api

from apps.api.model_governance_routes import router as legacy_router
from apps.api.package_history_exposure_errors import install as install_errors
from apps.api.package_history_public_gate import require_history_public_guard
from packages.domain import storage
from packages.domain.runtime import DomainError, clean, connection
from packages.model_governance import purpose_runtime, training
from packages.model_governance import repository as legacy_repository
from packages.rag.indexing import original_source_id
from packages.research import execution as old_execution
from packages.research import ledger as old_ledger
from packages.research import package_history_exposure_fence as read_fence
from packages.research import worker as old_worker
from tests.test_research_integration import client as old_client_fixture
from tests.test_research_integration import register, verify

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "deploy/sql/package-history-exposure-bridge.sql"
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_HISTORY_BRIDGE_PG") != "1",
    reason="fresh reviewed optional exposure bridge database required",
)


@pytest.fixture
def database(monkeypatch):
    source = native.database.__wrapped__()
    value = next(source)
    groups = {
        "legacy_train": "tender_model_train",
        "legacy_evaluate": "tender_model_evaluate",
        "legacy_research": "tender_research_worker",
    }
    with psycopg.connect(
        os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"], autocommit=True, row_factory=dict_row
    ) as admin:
        try:
            for purpose, group in groups.items():
                role = "fusion_history_bridge_" + purpose
                password = secrets.token_urlsafe(36)
                admin.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
                admin.execute(
                    sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(role))
                )
                value[purpose + "_dsn"] = make_conninfo(
                    value["api_dsn"], user=role, password=password
                )
            monkeypatch.setenv("MODEL_TRAIN_DATABASE_DSN", value["legacy_train_dsn"])
            monkeypatch.setenv("MODEL_EVALUATE_DATABASE_DSN", value["legacy_evaluate_dsn"])
            monkeypatch.setenv("RESEARCH_WORKER_DATABASE_DSN", value["legacy_research_dsn"])
            yield value
        finally:
            try:
                next(source)
            except StopIteration:
                pass
            for purpose in groups:
                admin.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier("fusion_history_bridge_" + purpose)
                    )
                )
            for group in (
                "tender_package_history_verify",
                "tender_package_history_train",
                "tender_package_history_evaluate",
                "tender_package_history_test_api",
            ):
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(group)))


def install(database):
    database["owner"].execute(BRIDGE.read_text())


@pytest.fixture
def public_api(database):
    # No history router is added/replaced here. Exercise main's production
    # include_router dependency and reject any unguarded duplicate path.
    source = native.scope_api.__wrapped__(database)
    value = next(source)
    routes = [
        route
        for route in value["app"].router.routes
        if getattr(getattr(route, "endpoint", None), "__module__", None)
        == "apps.api.package_historical_research"
    ]
    assert len(routes) == 10
    assert len({(tuple(sorted(route.methods)), route.path) for route in routes}) == 10
    assert all(
        any(
            dependency.call is require_history_public_guard
            for dependency in route.dependant.dependencies
        )
        for route in routes
    )
    try:
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture
def legacy_client(database, monkeypatch):
    source = old_client_fixture.__wrapped__(monkeypatch)
    value = next(source)
    value[0].app.include_router(legacy_router)
    install_errors(value[0].app)
    value[0].app.middleware_stack = None
    try:
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def old_training(client, cohort):
    web, _, headers, _ = client
    view = web.get("/api/v1/model-governance/cohorts/" + cohort["id"])
    response = web.post(
        "/api/v1/model-governance/training-jobs",
        json={"cohort_id": cohort["id"], "reason": "Actual legacy owned CPU software test"},
        headers=headers(view.headers["etag"]),
    )
    assert response.status_code == 201, response.text
    return response


def old_evaluation(client, training):
    web, _, headers, _ = client
    view = web.get("/api/v1/model-governance/jobs/" + training.json()["id"])
    response = web.post(
        "/api/v1/model-governance/evaluations",
        json={
            "training_job_id": training.json()["id"],
            "reason": "Synthetic independent final evaluation",
        },
        headers=headers(view.headers["etag"]),
    )
    assert response.status_code == 201, response.text
    return response


def assert_republished_cohort_rejected(client, cohort):
    """Exercise the actual API repository transaction with a new cohort identity."""
    with connection() as c:
        before = c.execute("SELECT count(*) AS n FROM model_governance.cohorts").fetchone()["n"]
        records = {}
        for collection, table in (
            ("members", "members"),
            ("chapters", "chapter_bindings"),
            ("parses", "parse_bindings"),
            ("evidence", "evidence_bindings"),
            ("sources", "source_bindings"),
        ):
            records[collection] = [
                {key: value for key, value in clean(row).items() if key != "cohort_id"}
                for row in c.execute(
                    sql.SQL("SELECT * FROM model_governance.{} WHERE cohort_id=%s").format(
                        sql.Identifier(table)
                    ),
                    (cohort["id"],),
                ).fetchall()
            ]
        exports = {
            row["purpose"]: row["payload"]
            for row in c.execute(
                "SELECT purpose,payload FROM model_governance.exports WHERE cohort_id=%s",
                (cohort["id"],),
            ).fetchall()
        }
        protocol_id = c.execute(
            "SELECT protocol_id FROM model_governance.cohorts WHERE id=%s", (cohort["id"],)
        ).fetchone()["protocol_id"]
    with pytest.raises(DomainError, match="最终登记时") as rejected, connection() as c:
        legacy_repository.publish_cohort(
            c,
            actor=client[1],
            run_id=UUID(cohort["run_id"]),
            protocol_id=protocol_id,
            exports=exports,
            records=records,
            condition='"explicit-existing-fixture-preview"',
            preview_tag='"explicit-existing-fixture-preview"',
            command=None,
        )
    assert rejected.value.code == "MODEL_COHORT_STALE"
    with connection() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM model_governance.cohorts").fetchone()["n"]
            == before
        )


def test_checked_atomic_install_keeps_function_oids_and_private_acl(database):
    owner = database["owner"]
    before = owner.execute(
        "SELECT 'model_governance.current_cohort(uuid)'::regprocedure::oid AS value"
    ).fetchone()["value"]
    install(database)
    assert (
        owner.execute(
            "SELECT 'model_governance.current_cohort(uuid)'::regprocedure::oid AS value"
        ).fetchone()["value"]
        == before
    )
    for key in (
        "api",
        "ordinary_api",
        "worker",
        "legacy_train",
        "legacy_evaluate",
        "legacy_research",
        "verify",
        "train",
        "evaluate",
    ):
        with psycopg.connect(database[key + "_dsn"], row_factory=dict_row) as c:
            assert not c.execute(
                "SELECT rolsuper OR rolbypassrls AS value FROM pg_roles WHERE rolname=current_user"
            ).fetchone()["value"]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(
                    "SELECT package_history_exposure_bridge.legacy_current_original(%s)",
                    (uuid4(),),
                )


def test_dependency_digest_drift_aborts_all_bridge_changes(database):
    owner = database["owner"]
    # A deliberately mismatched installer, not a changed production function.
    source = BRIDGE.read_text()
    needle = "OR p.proowner<>current_user::regrole"
    assert needle in source
    mismatched = source.replace(needle, "OR true OR p.proowner<>current_user::regrole", 1)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="function_drift"):
        owner.execute(mismatched)
    owner.execute("ROLLBACK")
    assert owner.execute(
        "SELECT to_regnamespace('package_history_exposure_bridge') IS NULL AS value"
    ).fetchone()["value"]
    install(database)


def test_public_guard_actual_http_native_only_all_paths_closed_full_install_positive(public_api):
    api = public_api
    base = "/api/v1/package-historical-research"
    identities = [str(uuid4()) for _ in range(7)]
    scope = (
        f"/api/v1/bids/{identities[0]}/packages/{identities[1]}/revisions/{identities[2]}"
        f"/technical-scopes/{identities[3]}"
    )
    paths = [
        scope
        + f"/historical-admission-context?submission_id={identities[4]}&outcome_id={identities[5]}",
        base + "/admissions/" + identities[6],
        base + "/cpu-protocol-template",
        base + "/cohorts/" + identities[6],
        base + "/jobs/" + identities[6],
    ]
    commands = [
        scope + "/historical-admissions",
        base + "/protocols",
        base + "/cohorts",
        base + "/cohorts/" + identities[6] + "/jobs",
        base + "/jobs/" + identities[6] + "/control",
    ]
    owner = api["database"]["owner"]
    assert owner.execute(
        "SELECT to_regprocedure('package_historical_research.freeze_cohort(uuid,timestamptz,timestamptz,jsonb,uuid,uuid)') IS NOT NULL AS value"
    ).fetchone()["value"]
    web = api["client"]
    for method, path in [("GET", p) for p in paths] + [("POST", p) for p in commands]:
        response = web.request(
            method,
            path,
            headers=native.headers(api),
            **({"json": {}} if method == "POST" else {}),
        )
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "PACKAGE_HISTORY_PUBLIC_GUARD_UNAVAILABLE"
        assert response.json()["details"] == {
            "configured": False,
            "reason": "installation_missing",
            "required_guard": "package-history-public-guard/1",
            "qualification_granted": False,
            "command_started": False,
        }
        assert "no-store" in response.headers["cache-control"]
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.commands WHERE command_kind LIKE 'package-history-%'"
        ).fetchone()["n"]
        == 0
    )
    install(api["database"])
    # The independent directory can be installed later without invalidating
    # core security contracts or adding directory reads to qualification.
    owner.execute((ROOT / "deploy/sql/package-history-directory.sql").read_text())
    template = web.get(base + "/cpu-protocol-template")
    assert template.status_code == 200, template.text
    assert template.json()["schema_configured"]
    created = web.post(
        base + "/protocols",
        json={
            "method_digest": template.json()["method_digest"],
            "seed": 17,
            "bootstrap_iterations": 100,
            "reason": "Actual guarded public command on a synthetic mechanism database",
        },
        headers=native.headers(api),
    )
    assert created.status_code == 201, created.text
    assert created.json()["formal_eligibility"] == "unavailable"
    for role in ("api", "ordinary_api"):
        with psycopg.connect(api["database"][role + "_dsn"], row_factory=dict_row) as c:
            c.execute("SET TRANSACTION READ ONLY")
            ready = c.execute(
                "SELECT package_history_exposure_bridge.readiness() AS value"
            ).fetchone()["value"]
            assert ready["configured"] and not ready["qualification_granted"]
            assert ready["checked_function_count"] == 58 and ready["checked_trigger_count"] == 11
    for key in (
        "worker",
        "verify",
        "train",
        "evaluate",
        "legacy_train",
        "legacy_evaluate",
        "legacy_research",
    ):
        with psycopg.connect(api["database"][key + "_dsn"]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT package_history_exposure_bridge.readiness()")
    for query in (
        "SELECT * FROM package_history_exposure_bridge.guard_contracts",
        "UPDATE package_history_exposure_bridge.guard_manifest SET contract_count=76",
        "SELECT * FROM package_history_exposure_bridge.live_guard_contracts()",
        "CREATE FUNCTION package_history_exposure_bridge.forged_readiness() RETURNS boolean LANGUAGE sql AS 'SELECT true'",
    ):
        with psycopg.connect(api["database"]["api_dsn"]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(query)


@pytest.mark.parametrize(
    "fault", ("old_guard_body", "disabled_exposure", "private_execute", "forged_readiness")
)
def test_public_guard_actual_http_detects_initial_schema_fault_before_command(public_api, fault):
    api = public_api
    # Explicit, isolated negative installation fixtures. Owner creates malformed
    # initial DDL only; no owner business operation or permission repair occurs.
    alterations = {
        "old_guard_body": "CREATE OR REPLACE FUNCTION model_governance.current_cohort(target uuid) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,model_governance,design,retrieval,pg_temp AS $fault$ BEGIN RETURN false; END $fault$;",
        "disabled_exposure": "ALTER TABLE model_governance.exposures DISABLE TRIGGER package_history_bridge_exposure;",
        "private_execute": "GRANT EXECUTE ON FUNCTION package_history_exposure_bridge.legacy_current_original(uuid) TO tender_api;",
        "forged_readiness": "CREATE OR REPLACE FUNCTION package_history_exposure_bridge.readiness() RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fault$ BEGIN RETURN '{\"configured\":true}'::jsonb; END $fault$;",
    }
    source = BRIDGE.read_text()
    before, after = source.rsplit("COMMIT;", 1)
    api["database"]["owner"].execute(before + alterations[fault] + "COMMIT;" + after)
    web = api["client"]
    response = web.get("/api/v1/package-historical-research/cpu-protocol-template")
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "PACKAGE_HISTORY_PUBLIC_GUARD_UNAVAILABLE"
    assert response.json()["details"]["reason"] == (
        "readiness_identity_changed" if fault == "forged_readiness" else "installed_guard_changed"
    )
    assert (
        api["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM design.commands WHERE command_kind LIKE 'package-history-%'"
        )
        .fetchone()["n"]
        == 0
    )


def test_actual_legacy_api_cpu_zero_and_prepared_plan_remain_valid_before_foreign_exposure(
    database, legacy_client
):
    cohort = legacy_cohort(legacy_client)
    with psycopg.connect(database["api_dsn"], row_factory=dict_row, autocommit=True) as cached:
        cached.execute(
            "PREPARE bridge_original_current(uuid) AS SELECT model_governance.current_cohort($1) AS value"
        )
        assert cached.execute(
            sql.SQL("EXECUTE bridge_original_current({})").format(sql.Literal(cohort["id"]))
        ).fetchone()["value"]
        install(database)
        assert cached.execute(
            sql.SQL("EXECUTE bridge_original_current({})").format(sql.Literal(cohort["id"]))
        ).fetchone()["value"]
    job = old_training(legacy_client, cohort)
    trained = purpose_runtime.launch("train", job.json()["id"])
    assert trained.returncode == 0, (trained.stdout, trained.stderr)
    evaluation = old_evaluation(legacy_client, job)
    evaluated = purpose_runtime.launch("evaluate", evaluation.json()["id"])
    assert evaluated.returncode == 0, (evaluated.stdout, evaluated.stderr)
    response = legacy_client[0].get("/api/v1/model-governance/jobs/" + evaluation.json()["id"])
    assert response.json()["state"] == "succeeded" and response.json()["current"]
    assert response.json()["result"]["payload"]["report"]["project_mae"] == 0
    receipt = (
        database["owner"]
        .execute(
            "SELECT * FROM package_history_exposure_bridge.exposure_receipts WHERE namespace='body'"
        )
        .fetchone()
    )
    assert receipt["cohort_id"] == UUID(cohort["id"])
    assert len(receipt["snapshot"]) == 1
    assert receipt["snapshot"][0]["entity"] == "body:" + cohort["items"][-1]["sample_id"]


def cross_cases(api, legacy_client, tmp_path):
    cases = [native.independent_case(api, tmp_path) for _ in range(3)]
    boundary = datetime.now(timezone.utc).isoformat()
    cases.extend(native.independent_case(api, tmp_path) for _ in range(2))
    with connection() as c:
        shared_blob = c.execute(
            "SELECT blob_id FROM document_versions WHERE id=%s",
            (cases[3]["member"].document_version_id,),
        ).fetchone()["blob_id"]
    old = legacy_cohort(legacy_client, final_blob_id=shared_blob)
    return cases, boundary, old, shared_blob


def test_actual_cached_old_paths_and_read_exposure_publish_race(
    api, legacy_client, database, tmp_path
):
    cases, boundary, old, shared_blob = cross_cases(api, legacy_client, tmp_path)
    w = cases[0]
    completed = old_training(legacy_client, old)
    result = purpose_runtime.launch("train", completed.json()["id"])
    assert result.returncode == 0, result.stdout
    evaluating = old_evaluation(legacy_client, completed)
    running, queued = old_training(legacy_client, old), old_training(legacy_client, old)
    token, evaluation_token = uuid4(), uuid4()
    with (
        psycopg.connect(database["api_dsn"], row_factory=dict_row, autocommit=True) as cached,
        psycopg.connect(
            database["legacy_train_dsn"], row_factory=dict_row, autocommit=True
        ) as trainer,
        psycopg.connect(
            database["legacy_evaluate_dsn"], row_factory=dict_row, autocommit=True
        ) as evaluator,
        psycopg.connect(
            database["legacy_research_dsn"], row_factory=dict_row, autocommit=True
        ) as researcher,
    ):
        cached.execute(
            "PREPARE old_current(uuid) AS SELECT model_governance.current_cohort($1) AS value"
        )
        trainer.execute(
            "PREPARE old_claim(uuid,uuid) AS SELECT model_governance.claim_job($1,$2) AS value"
        )
        trainer.execute(
            "PREPARE old_read(uuid,uuid,bigint) AS SELECT model_governance.read_training($1,$2,$3) AS value"
        )
        trainer.execute(
            "PREPARE old_renew(uuid,uuid,bigint) AS SELECT model_governance.renew_job($1,$2,$3) AS value"
        )
        trainer.execute(
            "PREPARE old_finish AS SELECT model_governance.finish_job($1,$2,$3,$4,$5) AS value"
        )
        evaluator.execute(
            "PREPARE old_final(uuid,uuid,bigint) AS SELECT model_governance.read_final($1,$2,$3) AS value"
        )
        researcher.execute(
            "PREPARE old_research_scope(uuid) AS SELECT design.lock_research_run_scope($1)"
        )

        def prepared(c, name, *args):
            return c.execute(
                sql.SQL("EXECUTE {}({})").format(
                    sql.Identifier(name), sql.SQL(",").join(sql.Literal(arg) for arg in args)
                )
            )

        assert prepared(cached, "old_current", old["id"]).fetchone()["value"]
        lease = prepared(trainer, "old_claim", running.json()["id"], token).fetchone()["value"]
        bound = prepared(
            trainer, "old_read", running.json()["id"], token, lease["fence"]
        ).fetchone()["value"]
        assert prepared(
            trainer, "old_renew", running.json()["id"], token, lease["fence"]
        ).fetchone()["value"]
        eval_lease = evaluator.execute(
            "SELECT model_governance.claim_job(%s,%s) AS value",
            (evaluating.json()["id"], evaluation_token),
        ).fetchone()["value"]
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="committed_exposure_required"
        ):
            prepared(
                evaluator,
                "old_final",
                evaluating.json()["id"],
                evaluation_token,
                eval_lease["fence"],
            )
        prepared(researcher, "old_research_scope", old["run_id"])
        install(database)
        assert prepared(cached, "old_current", old["id"]).fetchone()["value"]
        protocol = native.registered_protocol(w)
        cohort = native.freeze_cohort(w, protocol, cases, boundary)
        linked = next(
            m for m in cohort["members"] if m["admission_id"] == cases[3]["admission"]["id"]
        )
        assert linked["exclusion_reason"] == "group_spans_submission_split"
        native_training = native.job(w, cohort, "train")
        result, _ = native.cpu_child(w, native_training, tmp_path)
        assert result.returncode == 0, (result.stdout, result.stderr)
        native_eval = native.job(w, cohort, "evaluate")
        native_lease = native.claim(w, native_eval)
        arguments = (
            native_eval["job_id"],
            native_lease["generation"],
            native_lease["fence"],
            native_lease["owner"],
        )
        started, finished = Event(), Event()
        exposure_pid = []

        def expose():
            with psycopg.connect(database["evaluate_dsn"], row_factory=dict_row) as c:
                exposure_pid.append(
                    c.execute("SELECT pg_backend_pid() AS value").fetchone()["value"]
                )
                started.set()
                identity = c.execute(
                    "SELECT package_historical_research.open_final(%s,%s,%s,%s) AS value", arguments
                ).fetchone()["value"]
            finished.set()
            return identity

        with ThreadPoolExecutor(max_workers=1) as executor:
            # The real old read holds the common governance lock until commit.
            with trainer.transaction():
                fresh = prepared(
                    trainer, "old_read", running.json()["id"], token, lease["fence"]
                ).fetchone()["value"]
                assert fresh == bound
                future = executor.submit(expose)
                assert started.wait(3)
                waiting = False
                for _ in range(100):
                    waiting = cached.execute(
                        "SELECT EXISTS(SELECT FROM pg_locks WHERE pid=%s AND locktype='advisory' AND NOT granted) AS value",
                        (exposure_pid[0],),
                    ).fetchone()["value"]
                    if waiting:
                        break
                    time.sleep(0.02)
                assert waiting and not finished.is_set(), (
                    "Actual exposure must wait for the existing old read transaction"
                )
            exposure = future.result(timeout=15)
        assert finished.is_set()
        assert not prepared(cached, "old_current", old["id"]).fetchone()["value"]
        for c, name, args in (
            (trainer, "old_claim", (queued.json()["id"], uuid4())),
            (trainer, "old_read", (running.json()["id"], token, lease["fence"])),
            (trainer, "old_renew", (running.json()["id"], token, lease["fence"])),
            (
                evaluator,
                "old_final",
                (evaluating.json()["id"], evaluation_token, eval_lease["fence"]),
            ),
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
                prepared(c, name, *args)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
            evaluator.execute(
                "SELECT model_governance.open_final(%s,%s,%s,%s)",
                (evaluating.json()["id"], evaluation_token, eval_lease["fence"], uuid4()),
            )
        computed = training.run(bound["export"])
        sql_digest = trainer.execute(
            "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex') AS value",
            (Jsonb(computed),),
        ).fetchone()["value"]
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
            prepared(
                trainer,
                "old_finish",
                running.json()["id"],
                token,
                lease["fence"],
                sql_digest,
                Jsonb(computed),
            )
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="bridge_final_already_exposed"
        ):
            prepared(researcher, "old_research_scope", old["run_id"])

    web, _, headers, _ = legacy_client
    stale = web.get("/api/v1/model-governance/cohorts/" + old["id"])
    assert stale.status_code == 200 and not stale.json()["current"]
    denied = web.post(
        "/api/v1/model-governance/training-jobs",
        json={"cohort_id": old["id"], "reason": "Must not restart exposed historical material"},
        headers=headers(stale.headers["etag"]),
    )
    assert denied.status_code == 409 and denied.json()["code"] == "MODEL_COHORT_STALE"
    old_result = web.get("/api/v1/model-governance/jobs/" + completed.json()["id"])
    assert old_result.json()["state"] == "succeeded" and old_result.json()["result"]
    assert not old_result.json()["current"]
    for purpose, task in (("train", queued), ("evaluate", evaluating)):
        refused = purpose_runtime.launch(purpose, task.json()["id"])
        assert refused.returncode == 1, (refused.stdout, refused.stderr)
        assert json.loads(refused.stdout) == {"state": "failed", "code": "PURPOSE_JOB_FAILED"}
    assert_republished_cohort_rejected(legacy_client, old)
    receipt = (
        database["owner"]
        .execute(
            "SELECT * FROM package_history_exposure_bridge.exposure_receipts WHERE namespace='package' AND exposure_id=%s",
            (exposure,),
        )
        .fetchone()
    )
    assert receipt["cohort_id"] == UUID(cohort["id"])
    assert "body:" + old["items"][-1]["sample_id"] in {e["entity"] for e in receipt["snapshot"]}
    assert (
        database["owner"]
        .execute(
            "SELECT count(*) AS n FROM model_governance.results WHERE job_id=%s",
            (running.json()["id"],),
        )
        .fetchone()["n"]
        == 0
    )

    # Re-import through the actual current v2 body API reaches the shared guard.
    imported = legacy_item(legacy_client, year=2025, body_blob_id=shared_blob, historical_v1=False)
    official, _ = register(web, headers, imported)
    verify(web, headers, imported, official)
    rejected = web.post(
        f"/api/v1/bids/{imported['bid']}/submissions/{imported['submission']}/sample-admission",
        json={},
        headers=headers(),
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "PACKAGE_HISTORY_FINAL_ALREADY_EXPOSED"
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM samples WHERE submission_id=%s",
                (imported["submission"],),
            ).fetchone()["n"]
            == 0
        )


def test_unselected_later_unknown_bridge_expands_committed_exposure_and_survives_withdrawal(
    api, legacy_client, database, tmp_path
):
    cases, boundary, old, shared_blob = cross_cases(api, legacy_client, tmp_path)
    unrelated = legacy_cohort(legacy_client)
    w = cases[0]
    web, _, headers, _ = legacy_client
    install(database)
    assert web.get("/api/v1/model-governance/cohorts/" + unrelated["id"]).json()["current"]
    protocol = native.registered_protocol(w)
    cohort = native.freeze_cohort(w, protocol, cases, boundary)
    trained = native.job(w, cohort, "train")
    result, _ = native.cpu_child(w, trained, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    evaluated = native.job(w, cohort, "evaluate")
    result, _ = native.cpu_child(w, evaluated, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    owner = database["owner"]
    receipt = owner.execute(
        "SELECT * FROM package_history_exposure_bridge.exposure_receipts WHERE namespace='package'"
    ).fetchone()
    final_id = unrelated["items"][-1]["sample_id"]
    assert "body:" + final_id not in {row["entity"] for row in receipt["snapshot"]}
    assert web.get("/api/v1/model-governance/cohorts/" + unrelated["id"]).json()["current"]
    with connection() as c:
        member = c.execute(
            "SELECT project_id,group_id FROM model_governance.members WHERE cohort_id=%s AND sample_id=%s",
            (unrelated["id"], final_id),
        ).fetchone()
        unrelated_blob = c.execute(
            "SELECT blob_id FROM document_versions WHERE id=%s", (unrelated["items"][-1]["body"],)
        ).fetchone()["blob_id"]

    # A registered but unqualified intermediary is not selected in either cohort.
    # Its exact bytes join the exposed group to the previously independent project.
    bridge = legacy_item(
        legacy_client,
        year=2025,
        body_blob_id=shared_blob,
        historical_v1=False,
        project_id=member["project_id"],
        round_no=2,
    )
    unknown, _ = register(web, headers, bridge, kind="unknown", value=None)
    assert unknown.json()["value"] is None
    pending = web.post(
        f"/api/v1/bids/{bridge['bid']}/submissions/{bridge['submission']}/sample-admission",
        json={},
        headers=headers(),
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["admission"] == "pending" and not pending.json()["eligible_label_pair"]
    assert not web.get("/api/v1/model-governance/cohorts/" + unrelated["id"]).json()["current"]
    assert owner.execute(
        "SELECT package_history_exposure_bridge.has_foreign_exposure(%s::text[],'body',%s) AS value",
        (["body:" + final_id], unrelated["id"]),
    ).fetchone()["value"]
    expanded = owner.execute(
        "SELECT package_history_exposure_bridge.related_entities(%s::text[]) AS value",
        (receipt["seeds"],),
    ).fetchone()["value"]
    assert {"body:" + final_id, "body:" + pending.json()["id"]}.issubset(expanded)
    assert (
        owner.execute(
            "SELECT snapshot FROM package_history_exposure_bridge.exposure_receipts WHERE namespace='package' AND exposure_id=%s",
            (receipt["exposure_id"],),
        ).fetchone()["snapshot"]
        == receipt["snapshot"]
    )

    # Withdrawal or a mutable current group identifier cannot erase the prior relation.
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(cases[3]["source"])),),
        )
    aliases = owner.execute(
        "SELECT identity FROM package_history_exposure_bridge.entity_aliases WHERE entity=%s",
        ("body:" + final_id,),
    ).fetchall()
    assert str(member["group_id"]) in {row["identity"] for row in aliases}
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="sample_identity_immutable"),
        connection() as c,
    ):
        c.execute(
            "UPDATE samples SET known_at=known_at+interval '1 second' WHERE id=%s", (final_id,)
        )
    assert owner.execute(
        "SELECT package_history_exposure_bridge.has_foreign_exposure(%s::text[],'body',%s) AS value",
        (["body:" + final_id], unrelated["id"]),
    ).fetchone()["value"]

    # A new project/round and distinct sample ID still carry the linked original bytes.
    reimport = legacy_item(
        legacy_client,
        year=2025,
        body_blob_id=unrelated_blob,
        historical_v1=False,
    )
    official, _ = register(web, headers, reimport)
    verify(web, headers, reimport, official)
    denied = web.post(
        f"/api/v1/bids/{reimport['bid']}/submissions/{reimport['submission']}/sample-admission",
        json={},
        headers=headers(),
    )
    assert (
        denied.status_code == 409
        and denied.json()["code"] == "PACKAGE_HISTORY_FINAL_ALREADY_EXPOSED"
    ), denied.text
    old_report = native.sql_as(
        w, "api", "SELECT package_historical_research.job_view(%s) AS value", (evaluated["job_id"],)
    )
    assert old_report["state"] == "succeeded" and old_report["result"] and not old_report["current"]


def test_actual_legacy_final_exposure_prevents_native_new_cohort_and_preserves_old_report(
    api, legacy_client, database, tmp_path
):
    cases, boundary, old, _ = cross_cases(api, legacy_client, tmp_path)
    install(database)
    trained = old_training(legacy_client, old)
    result = purpose_runtime.launch("train", trained.json()["id"])
    assert result.returncode == 0, (result.stdout, result.stderr)
    evaluated = old_evaluation(legacy_client, trained)
    result = purpose_runtime.launch("evaluate", evaluated.json()["id"])
    assert result.returncode == 0, (result.stdout, result.stderr)
    protocol = native.registered_protocol(cases[0])
    with pytest.raises(
        psycopg.errors.ObjectNotInPrerequisiteState, match="package_history_final_already_exposed"
    ):
        native.freeze_cohort(cases[0], protocol, cases, boundary)
    report = legacy_client[0].get("/api/v1/model-governance/jobs/" + evaluated.json()["id"])
    assert report.status_code == 200 and report.json()["current"]
    assert report.json()["result"]["payload"]["report"]["project_mae"] == 0
    receipt = (
        database["owner"]
        .execute(
            "SELECT snapshot FROM package_history_exposure_bridge.exposure_receipts WHERE namespace='body'"
        )
        .fetchone()
    )
    assert "package:" + cases[3]["admission"]["id"] in {
        row["entity"] for row in receipt["snapshot"]
    }


class OneHeartbeat:
    def __init__(self):
        self.seen = False

    def wait(self, seconds):
        if self.seen:
            return True
        self.seen = True
        return False


def test_actual_research_worker_objects_are_idle_fenced_against_exposure_and_later_reads_refused(
    api, legacy_client, database, tmp_path, monkeypatch
):
    cases, boundary, old, _ = cross_cases(api, legacy_client, tmp_path)
    message, lease = research_attempt(legacy_client, old)
    # The original full qualification still runs when optional bridge SQL is absent.
    baseline = old_worker.packages_for_item(message, lease)
    assert baseline
    install(database)
    w = cases[0]
    protocol = native.registered_protocol(w)
    cohort = native.freeze_cohort(w, protocol, cases, boundary)
    trained = native.job(w, cohort, "train")
    result, _ = native.cpu_child(w, trained, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    evaluated = native.job(w, cohort, "evaluate")
    acquired = native.claim(w, evaluated)
    finished = Event()
    launched = []
    original_get = storage.get
    reads = []

    def expose():
        value = native.sql_as(
            w,
            "evaluate",
            "SELECT package_historical_research.open_final(%s,%s,%s,%s) AS value",
            native.lease_args(acquired),
        )
        finished.set()
        return value

    with ThreadPoolExecutor(max_workers=2) as executor:

        def read_original(key):
            reads.append(key)
            if not launched:
                launched.extend(
                    (
                        executor.submit(expose),
                        executor.submit(old_worker.heartbeat, message, lease, OneHeartbeat()),
                    )
                )
            waiting = 0
            for _ in range(100):
                waiting = (
                    database["owner"]
                    .execute(
                        "SELECT count(*) AS n FROM pg_locks WHERE locktype='advisory' AND classid=91143 AND objid=1 AND NOT granted"
                    )
                    .fetchone()["n"]
                )
                if waiting >= 2:
                    break
                time.sleep(0.01)
            assert waiting >= 2 and not finished.is_set()
            readers = (
                database["owner"]
                .execute(
                    "SELECT a.state,a.xact_start FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid "
                    "WHERE a.usename='fusion_history_bridge_legacy_research' AND l.locktype='advisory' "
                    "AND l.classid=91143 AND l.objid=1 AND l.granted"
                )
                .fetchall()
            )
            assert readers and all(
                row["state"] == "idle" and row["xact_start"] is None for row in readers
            )
            return original_get(key)

        monkeypatch.setattr(storage, "get", read_original)
        assert old_worker.packages_for_item(message, lease) == baseline
        assert len(reads) >= 2
        assert launched[0].result(timeout=15)
        # Whichever transaction wins after the session closes is linearized first.
        # A heartbeat cannot publish, reopen or clear the final exposure.
        try:
            launched[1].result(timeout=15)
        except psycopg.errors.ObjectNotInPrerequisiteState as error:
            assert "bridge_final_already_exposed" in str(error)
    assert finished.is_set()
    reads.clear()
    with pytest.raises(
        psycopg.errors.ObjectNotInPrerequisiteState, match="bridge_final_already_exposed"
    ):
        old_worker.packages_for_item(message, lease)
    assert reads == [], "A committed exposure must reject before any object read"
    for invoke in (
        lambda: old_worker.heartbeat(message, lease, OneHeartbeat()),
        lambda: old_execution.acquire(message),
        lambda: old_execution.finish(message, lease, error_code="EXPLICIT_SYNTHETIC_NO_SEND"),
        lambda: old_ledger.reserve(
            run_id=lease["run_id"],
            message=message,
            lease=lease,
            logical_key="synthetic-no-send",
            request_digest="1" * 64,
            profile_digest="2" * 64,
            reserved_fee="0.01",
        ),
    ):
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="bridge_final_already_exposed"
        ):
            invoke()
    with connection() as c:
        state = c.execute(
            "SELECT state,output FROM step_receipts WHERE operation_id=%s",
            (message["operation_id"],),
        ).fetchone()
        assert state["state"] == "running" and state["output"] is None
        assert (
            c.execute(
                "SELECT count(*) AS n FROM model_calls WHERE operation_id=%s",
                (message["operation_id"],),
            ).fetchone()["n"]
            == 0
        )


def test_research_object_error_cancel_timeout_release_fence_and_expired_lease_is_not_revived(
    legacy_client, database, monkeypatch
):
    old = legacy_cohort(legacy_client)
    message, lease = research_attempt(legacy_client, old)
    install(database)
    assert old_worker.packages_for_item(message, lease)
    original_get = storage.get

    def assert_released():
        with psycopg.connect(database["legacy_research_dsn"], row_factory=dict_row) as c:
            assert c.execute("SELECT pg_try_advisory_xact_lock(91143,1) AS value").fetchone()[
                "value"
            ]
        assert read_fence.signal.getitimer(read_fence.signal.ITIMER_REAL) == (0.0, 0.0)

    for error_type in (RuntimeError, KeyboardInterrupt):

        def fail(key, error_type=error_type):
            raise error_type("explicit synthetic object read interruption")

        monkeypatch.setattr(storage, "get", fail)
        with pytest.raises(error_type):
            old_worker.packages_for_item(message, lease)
        assert_released()

    # Real one-second deadline interrupts the object reader. Independent heartbeat
    # waits on the same session fence, then completes with the refreshed live lease.
    monkeypatch.setattr(read_fence, "READ_SECONDS", 1)
    heartbeat = []
    with ThreadPoolExecutor(max_workers=1) as executor:

        def slow(key):
            heartbeat.append(executor.submit(old_worker.heartbeat, message, lease, OneHeartbeat()))
            time.sleep(3)
            return original_get(key)

        monkeypatch.setattr(storage, "get", slow)
        started = time.monotonic()
        with pytest.raises(DomainError) as rejected:
            old_worker.packages_for_item(message, lease)
        assert rejected.value.code == "RESEARCH_SOURCE_READ_TIMEOUT"
        assert 0.8 <= time.monotonic() - started < 3
        assert heartbeat and heartbeat[0].result(timeout=10) is None
    assert_released()
    with connection() as c:
        current = c.execute(
            "SELECT lease_until>clock_timestamp()+interval '60 seconds' AS value FROM step_receipts WHERE operation_id=%s",
            (message["operation_id"],),
        ).fetchone()
        assert current["value"]
        # Explicit synthetic short lease, then let real clock expiry happen.
        c.execute(
            "UPDATE step_receipts SET lease_until=clock_timestamp()+interval '100 milliseconds' WHERE operation_id=%s",
            (message["operation_id"],),
        )
    time.sleep(0.15)
    reads = []

    def should_not_read(key):
        reads.append(key)
        return original_get(key)

    monkeypatch.setattr(read_fence, "READ_SECONDS", 45)
    monkeypatch.setattr(storage, "get", should_not_read)
    with pytest.raises(DomainError) as expired:
        old_worker.packages_for_item(message, lease)
    assert expired.value.code == "RESEARCH_EXECUTION_STALE" and not reads
    assert_released()
