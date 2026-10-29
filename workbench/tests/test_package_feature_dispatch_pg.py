"""Opt-in disposable PG binding/lease checks; no deployment or production access."""
# ruff: noqa: F401,F811

import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import test_package_history_pg as native
from psycopg.types.json import Jsonb
from test_package_history_pg import api

from packages.domain.review_identity import digest
from packages.model_governance import package_feature_dispatch as feature
from packages.model_governance import package_history_complete as complete
from packages.model_governance import package_history_cpu as cpu

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_FEATURE_DISPATCH_PG") != "1",
    reason="fresh disposable PG17 fixed feature dispatcher opt-in required",
)


@pytest.fixture
def database():
    source = native.database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        query = "SELECT oid,proowner,proacl FROM pg_proc WHERE pronamespace='package_historical_research'::regnamespace AND proname IN('claim_job','finish_job') ORDER BY oid"
        before = owner.execute(query).fetchall()
        for name in (
            "package-history-complete-material.sql",
            "package-history-feature-final.sql",
            "package-history-feature-evaluation.sql",
            "package-history-feature-dispatch.sql",
            "package-history-exposure-bridge.sql",
            "package-history-dispatch.sql",
        ):
            owner.execute((ROOT / "deploy/sql" / name).read_text())
        assert owner.execute(query).fetchall() == before
        yield value
    finally:
        source.close()


def prepared(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    lease = native.claim(w, task)
    binding = {
        "schema": feature.BINDING,
        "job_id": task["job_id"],
        "cohort_id": cohort["id"],
        "membership_digest": cohort["membership_digest"],
        "purpose": "train",
        "reference_digest": "a" * 64,
        "candidate_digest": None,
        "methods": feature.methods(),
    }
    return w, task, lease, binding


def publish(w, lease, value):
    return native.sql_as(
        w,
        "train",
        "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s) AS value",
        (*native.lease_args(lease), Jsonb(value), digest(value)),
    )


def test_guard_no_direct_binding_access_and_fresh_only(database):
    with psycopg.connect(database["api_dsn"]) as c:
        status = c.execute("SELECT package_history_exposure_bridge.readiness()").fetchone()[0]
        assert status["configured"] and status["contract_count"] == 76
    with psycopg.connect(database["train_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM package_historical_research.feature_dispatch_bindings")
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="fresh_install"):
        database["owner"].execute(
            (ROOT / "deploy/sql/package-history-feature-dispatch.sql").read_text()
        )
    database["owner"].execute("ROLLBACK")


def test_binding_is_idempotent_immutable_and_survives_generation_recovery(api, tmp_path):
    w, task, lease, binding = prepared(api, tmp_path)
    assert lease["dispatch_binding"] is None
    assert publish(w, lease, binding) and publish(w, lease, binding)
    changed = deepcopy(binding)
    changed["reference_digest"] = "b" * 64
    with pytest.raises(psycopg.errors.CheckViolation, match="binding_conflict"):
        publish(w, lease, changed)
    paused = native.control_job(w, task, "pause")
    resumed = native.control_job(w, paused, "resume")
    recovered = native.claim(w, resumed)
    assert recovered["dispatch_binding"] == binding
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="lease_invalid"):
        publish(w, lease, binding)
    assert publish(w, recovered, binding)


def test_wrong_cohort_and_baseline_fallback_cannot_publish(api, tmp_path):
    w, _, lease, binding = prepared(api, tmp_path)
    wrong = dict(binding, cohort_id=str(uuid4()))
    with pytest.raises(psycopg.errors.CheckViolation, match="binding_invalid"):
        publish(w, lease, wrong)
    assert publish(w, lease, binding)
    exported = native.sql_as(
        w,
        "train",
        "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value",
        native.lease_args(lease),
    )
    old_baseline = cpu.train(complete.training_export(exported))
    with pytest.raises(psycopg.errors.CheckViolation, match="result_mismatch"):
        publish(w, lease, old_baseline)
