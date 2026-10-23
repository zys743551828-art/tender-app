"""Real purpose LOGINs and CPU subprocess dispatch; all evidence and labels synthetic."""
# ruff: noqa: F401,F811

import json
import os
import shlex
import subprocess  # nosec B404
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import test_package_history_exposure_bridge_pg as bridge
import test_package_history_pg as native
from psycopg import sql
from psycopg.rows import dict_row

from packages.model_governance.common import digest

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "deploy/sql/package-history-dispatch.sql"
GROUPS = (
    "tender_package_history_verify",
    "tender_package_history_train",
    "tender_package_history_evaluate",
    "tender_package_history_test_api",
)
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_HISTORY_DISPATCH_PG") != "1",
    reason="explicit isolated Compose history dispatcher acceptance required",
)


@pytest.fixture
def database():
    dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    with psycopg.connect(dsn, autocommit=True) as admin:
        assert admin.info.dbname == "postgres"
        assert not admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)", (list(GROUPS),)
        ).fetchone(), (
            "dedicated history role names already occupied; do not repair another environment"
        )
        source = native.database.__wrapped__()
        try:
            value = next(source)
            bridge.install(value)
            value["owner"].execute(SQL.read_text())
            yield value
        finally:
            source.close()
            for name in GROUPS:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.fixture
def api(database):
    source = native.scope_api.__wrapped__(database)
    value = next(source)
    try:
        yield value
    finally:
        source.close()


def child(w, purpose, tmp_path, *, cycles=1, batch=5):
    path = tmp_path / (uuid4().hex + ".profile")
    path.write_text(
        "PACKAGE_HISTORY_"
        + purpose.upper()
        + "_DSN="
        + shlex.quote(w["database"][purpose + "_dsn"])
        + "\n"
    )
    path.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "deploy/package_history_dispatcher.py"),
            "--purpose",
            purpose,
            "--profile",
            str(path),
            "--cycles",
            str(cycles),
            "--batch-size",
            str(batch),
            "--poll-seconds",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )  # nosec B603
    receipts = [json.loads(line) for line in result.stdout.splitlines()]
    return result, receipts


def scan(w, purpose, *, after=None, limit=20):
    return native.sql_as(
        w,
        purpose,
        "SELECT package_historical_research.dispatch_candidates(%s,%s,%s,%s) AS value",
        (
            purpose,
            after["created_at"] if after else None,
            after["job_id"] if after else None,
            limit,
        ),
    )


def test_discovery_to_train_and_final_evaluate_uses_distinct_real_child_logins(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    train = native.job(w, cohort, "train")
    assert scan(w, "evaluate") == []
    lease = native.claim(w, train)
    observations = {}
    for setting in ("on", "off"):
        with psycopg.connect(w["database"]["train_dsn"], row_factory=dict_row) as c:
            c.execute("SET LOCAL statement_timeout='90s'")
            c.execute("SET LOCAL jit=" + setting)
            started = time.monotonic()
            document = c.execute(
                "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value",
                native.lease_args(lease),
            ).fetchone()["value"]
            observations[setting] = {
                "seconds": round(time.monotonic() - started, 3),
                "digest": digest(document),
            }
    assert observations["on"]["digest"] == observations["off"]["digest"]
    evidence = Path(os.environ.get("FUSION_HISTORY_DISPATCH_EVIDENCE", str(tmp_path)))
    (evidence / "history-dispatch-jit.json").write_text(json.dumps(observations, indent=2) + "\n")
    paused = native.control_job(w, train, "pause")
    native.control_job(w, paused, "resume")
    process, receipts = child(w, "train", tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert receipts[0]["result"]["completed"] == 1
    assert receipts[0]["result"]["outcomes"][0]["job_id"] == train["job_id"]
    training_receipts = receipts
    evaluate = native.job(w, cohort, "evaluate")
    assert scan(w, "train") == []
    process, receipts = child(w, "evaluate", tmp_path, cycles=2)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert [r["result"]["completed"] for r in receipts] == [1, 0]
    with psycopg.connect(w["database"]["api_dsn"]) as c:
        value = c.execute(
            "SELECT package_historical_research.job_view(%s)", (evaluate["job_id"],)
        ).fetchone()[0]
    assert value["state"] == "succeeded"
    assert value["result"]["report"]["denominator"] == 2
    assert (
        value["result"]["research_only"] and value["result"]["acceptance_decision"] == "unavailable"
    )
    assert all(r["result"]["paid_calls"] == r["result"]["provider_requests"] == 0 for r in receipts)
    (evidence / "history-dispatch-native.json").write_text(
        json.dumps(
            {
                "synthetic_business_evidence": True,
                "actual_cpu_subprocesses": True,
                "training": training_receipts,
                "evaluation": receipts,
                "evaluation_denominator": value["result"]["report"]["denominator"],
                "formal_eligibility": "unavailable",
                "paid_calls": 0,
            },
            indent=2,
        )
        + "\n"
    )


def test_bounded_cursor_skips_paused_active_and_terminal_work_and_preserves_generation(
    api, tmp_path
):
    cases, protocol, cohort, boundary = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    tasks = [native.job(w, cohort, "train")]
    for _ in range(2):
        other = native.freeze_cohort(w, protocol, cases, boundary)
        tasks.append(native.job(w, other, "train"))
    page = scan(w, "train", limit=1)
    assert len(page) == 1 and set(page[0]) == {"job_id", "generation", "created_at"}
    second = scan(w, "train", after=page[0], limit=1)
    assert len(second) == 1 and second[0]["job_id"] != page[0]["job_id"]
    native.control_job(w, tasks[0], "pause")
    assert tasks[0]["job_id"] not in [item["job_id"] for item in scan(w, "train")]
    lease = native.claim(w, tasks[1])
    assert tasks[1]["job_id"] not in [item["job_id"] for item in scan(w, "train")]
    # Only this disposable fixture shortens a lease; the real claim must raise its fence.
    w["database"]["owner"].execute(
        "UPDATE package_historical_research.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
        (tasks[1]["job_id"],),
    )
    assert tasks[1]["job_id"] in [item["job_id"] for item in scan(w, "train")]
    replacement = native.claim(w, tasks[1])
    assert replacement["fence"] == lease["fence"] + 1
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        native.sql_as(
            w,
            "train",
            "SELECT package_historical_research.renew_job(%s,%s,%s,%s)",
            native.lease_args(lease),
        )
    paused = native.sql_as(
        w, "api", "SELECT package_historical_research.job_view(%s) AS value", (tasks[0]["job_id"],)
    )
    resumed = native.control_job(w, paused, "resume")
    assert (
        next(item for item in scan(w, "train") if item["job_id"] == tasks[0]["job_id"])[
            "generation"
        ]
        == resumed["generation"]
    )


def test_two_dispatchers_publish_only_one_owned_result(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(executor.map(lambda _: child(w, "train", tmp_path), range(2)))
    assert all(process.returncode == 0 for process, _ in runs)
    assert sum(receipt["result"]["completed"] for _, receipts in runs for receipt in receipts) in (
        1,
        2,
    )
    # A race may replay the already succeeded ACK; publication remains unique.
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM package_historical_research.results WHERE job_id=%s",
            (task["job_id"],),
        )
        .fetchone()["n"]
        == 1
    )
    assert scan(w, "train") == []


def test_discovery_role_bounds_and_complete_guard_fail_closed(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    native.job(w, cohort, "train")
    for purpose in ("api", "ordinary_api", "verify"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            native.sql_as(
                w,
                purpose,
                "SELECT package_historical_research.dispatch_candidates('train',NULL,NULL,1)",
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        native.sql_as(
            w,
            "train",
            "SELECT package_historical_research.dispatch_candidates('evaluate',NULL,NULL,1)",
        )
    for statement in (
        "SELECT * FROM package_historical_research.jobs",
        "SELECT * FROM package_historical_research.proofs",
        "SELECT * FROM package_history_exposure_bridge.guard_contracts",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            native.sql_as(w, "train", statement)
    for limit in (0, 21):
        with pytest.raises(psycopg.errors.CheckViolation):
            scan(w, "train", limit=limit)
    owner = w["database"]["owner"]
    # Damage and restore only this synthetic test database, never a runtime database.
    original = owner.execute(
        "SELECT pg_get_functiondef('package_history_exposure_bridge.readiness()'::regprocedure) AS source"
    ).fetchone()["source"]
    try:
        owner.execute(
            "CREATE OR REPLACE FUNCTION package_history_exposure_bridge.readiness() RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN RETURN '{}'::jsonb; END $$"
        )
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="dispatch_guard_unavailable"
        ):
            scan(w, "train")
    finally:
        owner.execute(original)
    assert len(scan(w, "train")) == 1
    try:
        owner.execute(
            "ALTER TABLE package_historical_research.exposures DISABLE TRIGGER package_history_bridge_exposure"
        )
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="dispatch_guard_unavailable"
        ):
            scan(w, "train")
    finally:
        owner.execute(
            "ALTER TABLE package_historical_research.exposures ENABLE TRIGGER package_history_bridge_exposure"
        )
    assert len(scan(w, "train")) == 1
