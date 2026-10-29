"""Opt-in fresh PG exposure extension; no production or real quality claims."""
# ruff: noqa: F401,F811

import os
from pathlib import Path

import psycopg
import pytest
import test_package_history_pg as native
from psycopg.types.json import Jsonb
from test_package_feature_final_pg import test_old_baseline_still_exposes_and_evaluates
from test_package_history_pg import api

from packages.domain.review_identity import digest
from packages.model_governance import package_history_cpu as cpu

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_FEATURE_EVALUATION_PG") != "1",
    reason="fresh disposable PG17 feature evaluation opt-in required",
)


@pytest.fixture
def database():
    source = native.database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        for name in (
            "package-history-feature-final.sql",
            "package-history-feature-evaluation.sql",
            "package-history-exposure-bridge.sql",
        ):
            owner.execute((ROOT / "deploy/sql" / name).read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def test_guard_and_no_direct_binding_authority(database):
    with psycopg.connect(database["api_dsn"]) as c:
        readiness = c.execute("SELECT package_history_exposure_bridge.readiness()").fetchone()[0]
        assert readiness["configured"] and readiness["contract_count"] == 76
    with psycopg.connect(database["evaluate_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM package_historical_research.feature_final_exposures")
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="fresh_install"):
        database["owner"].execute(
            (ROOT / "deploy/sql/package-history-feature-evaluation.sql").read_text()
        )
    database["owner"].execute("ROLLBACK")


def test_feature_candidate_without_frozen_predictions_cannot_expose(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    lease = native.claim(w, task)
    args = native.lease_args(lease)
    bundle = native.sql_as(
        w, "train", "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value", args
    )
    trained = cpu.train(bundle)
    # Deliberately incomplete worker result is not a valid feature candidate.
    # The existing baseline sink accepts extras; exposure must still refuse it.
    trained["complete_feature_training"] = {"status": "unavailable"}
    native.sql_as(
        w,
        "train",
        "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s) AS value",
        (*args, Jsonb(trained), digest(trained)),
    )
    task = native.job(w, cohort, "evaluate")
    lease = native.claim(w, task)
    args = native.lease_args(lease)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="predictions_required"):
        native.sql_as(
            w,
            "evaluate",
            "SELECT package_historical_research.open_final(%s,%s,%s,%s) AS value",
            args,
        )
    with pytest.raises(
        psycopg.errors.ObjectNotInPrerequisiteState, match="committed_exposure_required"
    ):
        native.sql_as(
            w,
            "evaluate",
            "SELECT package_historical_research.read_final(%s,%s,%s,%s) AS value",
            args,
        )
