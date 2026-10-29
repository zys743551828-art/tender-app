"""Fresh disposable PG17 extension acceptance; never enabled by default."""
# ruff: noqa: F811

import os
from pathlib import Path

import psycopg
import pytest
import test_package_history_pg as native
from psycopg.types.json import Jsonb
from test_package_history_pg import api  # noqa: F401

from packages.domain.review_identity import digest
from packages.model_governance import package_history_cpu as cpu

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "deploy/sql/package-history-feature-final.sql"
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_FEATURE_FINAL_PG") != "1",
    reason="fresh disposable PG17 final prediction extension opt-in required",
)


@pytest.fixture
def database():
    source = native.database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        query = "SELECT oid,proowner,proacl FROM pg_proc WHERE pronamespace='package_historical_research'::regnamespace AND proname IN('claim_job','finish_job','open_final') ORDER BY oid"
        before = owner.execute(query).fetchall()
        owner.execute(SQL.read_text())
        assert owner.execute(query).fetchall() == before
        owner.execute((ROOT / "deploy/sql/package-history-exposure-bridge.sql").read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def test_fresh_only_unchanged_acl_and_guard(database):
    owner = database["owner"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="fresh_install"):
        owner.execute(SQL.read_text())
    owner.execute("ROLLBACK")
    with psycopg.connect(database["api_dsn"]) as c:
        readiness = c.execute("SELECT package_history_exposure_bridge.readiness()").fetchone()[0]
        assert readiness["configured"] and readiness["contract_count"] == 76
    with psycopg.connect(database["evaluate_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM package_historical_research.feature_final_predictions")


def test_old_baseline_still_exposes_and_evaluates(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    lease = native.claim(w, task)
    args = native.lease_args(lease)
    bundle = native.sql_as(
        w, "train", "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value", args
    )
    trained = cpu.train(bundle)
    native.sql_as(
        w,
        "train",
        "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s) AS value",
        (*args, Jsonb(trained), digest(trained)),
    )
    task = native.job(w, cohort, "evaluate")
    lease = native.claim(w, task)
    assert "feature_final_input" not in lease
    args = native.lease_args(lease)
    native.sql_as(
        w, "evaluate", "SELECT package_historical_research.open_final(%s,%s,%s,%s) AS value", args
    )
    exported = native.sql_as(
        w, "evaluate", "SELECT package_historical_research.read_final(%s,%s,%s,%s) AS value", args
    )
    evaluated = cpu.evaluate(exported)
    native.sql_as(
        w,
        "evaluate",
        "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s) AS value",
        (*args, Jsonb(evaluated), digest(evaluated)),
    )
