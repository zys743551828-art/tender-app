"""Opt-in disposable PG checks for the versioned reader; no production fixtures."""
# ruff: noqa: F811

import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
import test_package_history_pg as native
from psycopg.types.json import Jsonb
from test_package_history_pg import api  # noqa: F401

from packages.domain.runtime import connection
from packages.model_governance import package_history_complete as complete
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import digest
from packages.rag.indexing import original_source_id

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "deploy/sql/package-history-complete-material.sql"
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_HISTORY_COMPLETE_PG") != "1",
    reason="fresh disposable PG17 complete-material history reader opt-in required",
)


@pytest.fixture
def database():
    source = native.database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        query = "SELECT oid,proowner,proacl FROM pg_proc WHERE oid='package_historical_research.read_training(uuid,bigint,bigint,uuid)'::regprocedure"
        before = owner.execute(query).fetchone()
        owner.execute(SQL.read_text())
        assert owner.execute(query).fetchone() == before
        owner.execute((ROOT / "deploy/sql/package-history-exposure-bridge.sql").read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def test_native_training_export_exact_admissions_and_existing_result_sink(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    lease = native.claim(w, task)
    args = native.lease_args(lease)
    exported = native.sql_as(
        w, "train", "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value", args
    )
    assert exported["schema"] == complete.EXPORT
    expected = {case["admission"]["id"] for case in cases[:3]}
    assert {b["admission_id"] for b in exported["material_bindings"]} == expected
    assert {r["id"] for r in exported["training_export"]["rows"]} == expected
    assert exported["bindings_digest"] == digest(exported["material_bindings"])
    assert all("label" not in b and "target" not in b for b in exported["material_bindings"])
    result = cpu.train(complete.training_export(exported))
    native.sql_as(
        w,
        "train",
        "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s) AS value",
        (*args, Jsonb(result), digest(result)),
    )
    view = native.sql_as(
        w, "api", "SELECT package_historical_research.job_view(%s) AS value", (task["job_id"],)
    )
    assert view["result"] == result and view["state"] == "succeeded"


def test_existing_acl_guard_snapshot_and_fresh_install_only(database):
    owner = database["owner"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="fresh_install"):
        owner.execute(SQL.read_text())
    owner.execute("ROLLBACK")
    with psycopg.connect(database["api_dsn"]) as c:
        result = c.execute("SELECT package_history_exposure_bridge.readiness()").fetchone()[0]
        assert result["configured"] and result["contract_count"] == 76
    for role in ("evaluate", "verify", "api"):
        with psycopg.connect(database[role + "_dsn"]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(
                    "SELECT package_historical_research.read_training(%s,1,1,%s)",
                    (uuid4(), uuid4()),
                )


def test_withdrawal_after_claim_blocks_reader_and_publication(api, tmp_path):
    cases, _, cohort, _ = native.cohort_fixture(api, tmp_path)
    w = cases[0]
    task = native.job(w, cohort, "train")
    lease = native.claim(w, task)
    args = native.lease_args(lease)
    exported = native.sql_as(
        w, "train", "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value", args
    )
    result = cpu.train(complete.training_export(exported))
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(cases[0]["source"])),),
        )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
        native.sql_as(
            w,
            "train",
            "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value",
            args,
        )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
        native.sql_as(
            w,
            "train",
            "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s) AS value",
            (*args, Jsonb(result), digest(result)),
        )
