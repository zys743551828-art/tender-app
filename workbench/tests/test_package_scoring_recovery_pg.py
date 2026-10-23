"""Independent-role receipt reconciliation against a new physical mechanism DB.

Provider receipts are owner-registered synthetic evidence. These checks do not
qualify a real provider, historical sample, numeric prediction or formal score.
"""
# ruff: noqa: F401,F811

import json
import os
import secrets
import shlex
import subprocess  # nosec B404
import sys
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
import test_package_scoring_pg as base
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_package_scoring_pg import api, exact, requirements, world

from packages.domain.runtime import connection, sha
from packages.model_governance import package_scoring_profile as method

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_SCORE_RECOVERY_PG") != "1",
    reason="fresh isolated reconciliation database explicitly required",
)


@pytest.fixture(scope="module")
def database():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            base,
            "EXTENSIONS",
            (*base.EXTENSIONS, "deploy/sql/package-score-reconciliation.sql"),
        )
        source = base.database.__wrapped__()
        values = next(source)
        owner = values["owner"]
        role = "fusion_package_score_reconciler"
        password = secrets.token_urlsafe(36)
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        owner.execute(
            sql.SQL("GRANT tender_package_score_test_reconciler TO {}").format(sql.Identifier(role))
        )
        values["reconciler_dsn"] = make_conninfo(values["score_dsn"], user=role, password=password)
        try:
            yield values
        finally:
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            try:
                next(source)
            except StopIteration:
                pass


def unresolved(w, *, state="unknown"):
    saved, identity = base.prepare(w)
    job = base.start(w, identity)
    lease = base.claim(w, job)
    owned = base.worker(
        w,
        "SELECT package_score_execution.owned_input(%s,%s,%s,%s) AS value",
        base.lease_args(lease),
    )
    unit = owned["chapters"][0]
    reserved = base.worker(
        w,
        "SELECT package_score_execution.reserve_call(%s,%s,%s,%s,%s,1,%s,%s,%s) AS value",
        (
            *base.lease_args(lease),
            unit["id"],
            sha(method.request_for(unit["package"])),
            method.digest(),
            str(method.conservative_fee(base.prices())),
        ),
    )
    if state == "unknown":
        base.worker(
            w,
            "SELECT package_score_execution.settle_call(%s,%s,'unknown',NULL,NULL) AS value",
            (reserved["call_id"], lease["owner"]),
        )
    return {
        "scope": saved,
        "input": identity,
        "job": job,
        "lease": lease,
        "unit": unit,
        "call": str(reserved["call_id"]),
    }


def native_call(w, call_id):
    return (
        w["database"]["owner"]
        .execute(
            "SELECT to_jsonb(c) AS snapshot,design.package_technical_digest(to_jsonb(c)) AS digest FROM score_execution.calls c WHERE id=%s",
            (call_id,),
        )
        .fetchone()
    )


def registered_receipt(w, case, *, resolution="succeeded", alter=None, validity="1 hour"):
    original = native_call(w, case["call"])
    call = original["snapshot"]
    data = base.response(case["unit"]["package"])
    raw = {
        "schema": "controlled-score-response/1",
        "execution_purpose": "score",
        "data": data,
        "content": json.dumps(data),
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        "model": "deepseek-flash",
        "request_id": "synthetic-delayed-" + base.uid(),
        "response_id": "synthetic-delayed-" + base.uid(),
        "finish_reason": "stop",
        "request_digest": call["request_digest"],
        "profile_digest": method.digest(),
        "formal_scoring_eligible": False,
        "fee_basis": "usage_price_estimate",
    }
    values = {"expected": original["digest"], "raw": raw, "request": call["request_digest"]}
    if alter:
        alter(values)
    raw_text = json.dumps(values["raw"], ensure_ascii=False) if resolution == "succeeded" else None
    raw_digest = sha(raw_text.encode()) if raw_text else None
    record = {
        "schema": "isolated-package-score-provider-receipt/1",
        "origin": "synthetic",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "request_digest": values["request"],
        "profile_digest": method.digest(),
        "provider_receipt_id": "synthetic-receipt-" + base.uid(),
        "observed_state": resolution,
        "response_digest": raw_digest,
    }
    record_text = json.dumps(record, ensure_ascii=False)
    identity = base.uid()
    w["database"]["owner"].execute(
        "WITH stamp AS (SELECT clock_timestamp() AS at) INSERT INTO package_score_execution.reconciliation_receipts(id,database_oid,call_id,expected_call_digest,origin,resolution,provider_record,provider_record_digest,raw_response,raw_response_digest,observed_at,created_at,valid_until) SELECT %s,(SELECT oid FROM pg_database WHERE datname=current_database()),%s,%s,'synthetic',%s,%s,%s,%s,%s,at,at,at+%s::interval FROM stamp",
        (
            identity,
            case["call"],
            values["expected"],
            resolution,
            record_text,
            sha(record_text.encode()),
            raw_text,
            raw_digest,
            validity,
        ),
    )
    return identity


def reconcile(
    w, receipt, *, key=None, reason="Synthetic independent provider receipt reconciliation"
):
    with psycopg.connect(w["database"]["reconciler_dsn"], row_factory=dict_row) as c:
        return c.execute(
            "SELECT package_score_execution.reconcile_call(%s,%s,%s) AS value",
            (receipt, key or base.uid(), reason),
        ).fetchone()["value"]


def reconciliation_child(w, receipt, tmp_path, *, key=None, dsn=None):
    profile = tmp_path / (base.uid() + ".env")
    profile.write_text(
        "PACKAGE_SCORE_RECONCILIATION_DSN="
        + shlex.quote(dsn or w["database"]["reconciler_dsn"])
        + "\n"
    )
    profile.chmod(0o600)
    command = [
        sys.executable,
        "-I",
        str(ROOT / "deploy/package_scoring_reconcile.py"),
        "--profile",
        str(profile),
        "--receipt-id",
        receipt,
        "--command-key",
        key or base.uid(),
        "--reason",
        "Synthetic independently recorded delayed response; no provider resend",
    ]
    result = subprocess.run(  # nosec B603
        command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.stdout.strip(), result.stderr
    value = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == (0 if value["ok"] else 2), result.stderr
    return value


def resumed_child(w, case, generation, tmp_path):
    profile = tmp_path / (base.uid() + ".env")
    profile.write_text(
        "PACKAGE_SCORE_DATABASE_DSN=" + shlex.quote(w["database"]["score_dsn"]) + "\n"
    )
    profile.chmod(0o600)
    fixture = tmp_path / (base.uid() + ".json")
    base.http_fixture(w, case["input"], fixture)
    value = json.loads(fixture.read_text())
    value["responses"] = value["responses"][1:]
    fixture.write_text(json.dumps(value))
    result = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-I",
            str(ROOT / "deploy/package_scoring_worker.py"),
            "--profile",
            str(profile),
            "--job-id",
            case["job"],
            "--generation",
            str(generation),
            "--mechanism-response-fixture",
            str(fixture),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_actual_reconciler_child_preserves_unknown_then_worker_finishes_other_five_calls(
    exact, tmp_path
):
    case = unresolved(exact)
    before = native_call(exact, case["call"])["snapshot"]
    receipt = registered_receipt(exact, case)
    output = reconciliation_child(exact, receipt, tmp_path)
    assert output["ok"]
    result = output["receipt"]
    assert result["previous_state"] == "unknown" and result["state"] == "succeeded"
    assert result["provider_requests"] == 0 and result["paid_calls"] == 0
    assert result["generation"] == 2 and Decimal(result["reserved_fee_after"]) == 0
    assert Decimal(result["estimated_fee_after"]) == Decimal("0.0000016")
    assert not any(
        result[key] for key in ("formal_scoring_eligible", "training_eligible", "metrics_eligible")
    )
    stored = (
        exact["database"]["owner"]
        .execute(
            "SELECT * FROM package_score_execution.reconciliations WHERE call_id=%s",
            (case["call"],),
        )
        .fetchone()
    )
    assert stored["previous_call"] == before
    assert stored["settled_call"] == native_call(exact, case["call"])["snapshot"]
    with connection() as c:
        generation = c.execute(
            "SELECT package_score_execution.change_job(%s,%s,'resume',%s,'continue only remaining independent calls') AS value",
            (case["job"], result["generation"], exact["actor"]),
        ).fetchone()["value"]
    completed = resumed_child(exact, case, generation, tmp_path)
    assert completed["mock_http_calls"] == 5 and completed["paid_calls"] == 0
    view = base.view(case["job"])
    assert view["state"] == "succeeded" and view["calls"] == [{"state": "succeeded", "count": 6}]
    assert all(item["valid_replicates"] == 3 for item in view["result"]["document"]["items"])
    assert view["result"]["document"]["numeric_prediction"] is None


def test_proven_not_sent_releases_reserve_but_does_not_authorize_resend(exact):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case, resolution="not_sent")
    result = reconcile(exact, receipt)
    assert result["state"] == "not_sent"
    view = base.view(case["job"])
    assert view["state"] == "paused" and Decimal(view["reserved_fee"]) == 0
    assert Decimal(view["estimated_fee"]) == 0
    with pytest.raises(psycopg.Error) as error, connection() as c:
        c.execute(
            "SELECT package_score_execution.change_job(%s,%s,'resume',%s,'not automatic permission')",
            (case["job"], result["generation"], exact["actor"]),
        )
    assert error.value.sqlstate == "55000"
    _, new_input = base.prepare(exact, saved=case["scope"])
    with pytest.raises(psycopg.Error) as error:
        base.start(exact, new_input)
    assert error.value.sqlstate == "55000"


def test_active_reservation_requires_expired_lease_before_reconciliation(exact):
    case = unresolved(exact, state="reserved")
    receipt = registered_receipt(exact, case)
    before = native_call(exact, case["call"])
    with pytest.raises(psycopg.Error) as error:
        reconcile(exact, receipt)
    assert error.value.sqlstate == "55000" and native_call(exact, case["call"]) == before
    exact["database"]["owner"].execute(
        "UPDATE score_execution.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
        (case["job"],),
    )
    result = reconcile(exact, receipt)
    assert result["previous_state"] == "reserved" and result["state"] == "succeeded"
    assert base.view(case["job"])["state"] == "paused"


def test_original_receipt_replay_survives_source_change_without_rebilling(exact):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case)
    key = base.uid()
    result = reconcile(exact, receipt, key=key)
    source_id = case["unit"]["package"]["source_snapshot"][0]["ancestor_id"]
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (source_id,),
        )
    assert reconcile(exact, receipt, key=key) == result
    assert not base.view(case["job"])["source_current"]
    assert Decimal(base.view(case["job"])["estimated_fee"]) == Decimal("0.0000016")
    with pytest.raises(psycopg.Error) as error:
        reconcile(exact, receipt, key=key, reason="different operation")
    assert error.value.sqlstate == "23505"
    with pytest.raises(psycopg.Error) as error:
        reconcile(exact, receipt)
    assert error.value.sqlstate == "55000"
    owner = exact["database"]["owner"]
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM design.audit_entries WHERE event_type='package_score.call_reconciled' AND payload->>'call_id'=%s",
            (case["call"],),
        ).fetchone()["n"]
        == 1
    )


@pytest.mark.parametrize(
    "alter",
    [
        lambda value: value.update(expected="0" * 64),
        lambda value: value.update(request="1" * 64),
        lambda value: value["raw"].update(request_digest="2" * 64),
        lambda value: value["raw"].update(profile_digest="3" * 64),
        lambda value: value["raw"].update(model="unbound-model"),
        lambda value: value["raw"]["usage"].update(total_tokens=999),
        lambda value: value["raw"]["usage"].update(prompt_tokens=-1, total_tokens=29),
        lambda value: value["raw"]["usage"].update(prompt_tokens=2000000, total_tokens=2000030),
    ],
)
def test_receipt_mismatch_or_invalid_usage_cannot_change_unknown_or_release_reserve(exact, alter):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case, alter=alter)
    before = native_call(exact, case["call"])
    before_job = base.view(case["job"])
    with pytest.raises(psycopg.Error) as error:
        reconcile(exact, receipt)
    assert error.value.sqlstate == "23514"
    assert native_call(exact, case["call"]) == before
    after_job = base.view(case["job"])
    assert after_job["estimated_fee"] == before_job["estimated_fee"]
    assert after_job["reserved_fee"] == before_job["reserved_fee"]
    assert after_job["generation"] == before_job["generation"]


def test_expired_receipt_is_rejected_before_accounting(exact):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case, validity="10 milliseconds")
    time.sleep(0.03)
    before = native_call(exact, case["call"])
    with pytest.raises(psycopg.Error) as error:
        reconcile(exact, receipt)
    assert error.value.sqlstate == "55000" and native_call(exact, case["call"]) == before


def test_source_withdrawal_still_allows_truthful_reconciliation_without_result(exact):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case)
    source_id = case["unit"]["package"]["source_snapshot"][0]["ancestor_id"]
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (source_id,),
        )
    result = reconcile(exact, receipt)
    assert result["state"] == "succeeded"
    view = base.view(case["job"])
    assert not view["source_current"] and view["result"] is None
    with pytest.raises(psycopg.Error) as error, connection() as c:
        c.execute(
            "SELECT package_score_execution.change_job(%s,%s,'resume',%s,'source still withdrawn')",
            (case["job"], result["generation"], exact["actor"]),
        )
    assert error.value.sqlstate == "55000"


def test_purpose_separation_and_owner_only_receipts(exact, tmp_path):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case)
    for key in ("api_dsn", "ordinary_api_dsn", "worker_dsn", "score_dsn"):
        with psycopg.connect(exact["database"][key]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(
                    "SELECT package_score_execution.reconcile_call(%s,%s,'not this purpose')",
                    (receipt, base.uid()),
                )
    for key in ("api_dsn", "ordinary_api_dsn", "worker_dsn", "score_dsn", "reconciler_dsn"):
        for query in (
            "SELECT * FROM package_score_execution.reconciliation_receipts",
            "INSERT INTO package_score_execution.reconciliation_receipts(id) VALUES(gen_random_uuid())",
        ):
            with psycopg.connect(exact["database"][key]) as c:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute(query)
    for query in (
        "SELECT * FROM design.outcomes",
        "SELECT * FROM score_execution.calls",
        "SELECT * FROM package_score_execution.reconciliations",
    ):
        with psycopg.connect(exact["database"]["reconciler_dsn"]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(query)
    result = reconciliation_child(exact, receipt, tmp_path, dsn=exact["database"]["score_dsn"])
    assert result["code"] == "PACKAGE_SCORE_RECONCILIATION_ROLE_INVALID"
    assert native_call(exact, case["call"])["snapshot"]["state"] == "unknown"


def test_mixed_reconciler_role_is_rejected_by_sql_and_runtime(exact, tmp_path):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case)
    owner = exact["database"]["owner"]
    owner.execute("GRANT tender_api TO fusion_package_score_reconciler")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reconcile(exact, receipt)
        result = reconciliation_child(exact, receipt, tmp_path)
        assert result["code"] == "PACKAGE_SCORE_RECONCILIATION_ROLE_INVALID"
    finally:
        owner.execute("REVOKE tender_api FROM fusion_package_score_reconciler")


def test_failed_audit_rolls_back_state_fees_and_receipt_atomically(exact):
    case = unresolved(exact)
    receipt = registered_receipt(exact, case)
    before = native_call(exact, case["call"])
    before_job = base.view(case["job"])
    owner = exact["database"]["owner"]
    owner.execute(
        "CREATE FUNCTION package_score_execution.reject_test_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.event_type='package_score.call_reconciled' THEN RAISE EXCEPTION 'synthetic audit failure'; END IF; RETURN NEW; END $$"
    )
    owner.execute(
        "CREATE TRIGGER reject_test_audit BEFORE INSERT ON design.audit_entries FOR EACH ROW EXECUTE FUNCTION package_score_execution.reject_test_audit()"
    )
    try:
        with pytest.raises(psycopg.Error) as error:
            reconcile(exact, receipt)
        assert error.value.sqlstate == "P0001"
        assert native_call(exact, case["call"]) == before
        after_job = base.view(case["job"])
        assert after_job["reserved_fee"] == before_job["reserved_fee"]
        assert after_job["estimated_fee"] == before_job["estimated_fee"]
        assert after_job["generation"] == before_job["generation"]
        assert (
            owner.execute(
                "SELECT count(*) AS n FROM package_score_execution.reconciliations WHERE call_id=%s",
                (case["call"],),
            ).fetchone()["n"]
            == 0
        )
    finally:
        owner.execute("DROP TRIGGER reject_test_audit ON design.audit_entries")
        owner.execute("DROP FUNCTION package_score_execution.reject_test_audit()")
