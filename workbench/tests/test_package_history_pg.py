"""Native package history on fresh PG; actual isolated roles and synthetic evidence.

This suite never installs the old WIP retrospective SQL and cannot establish real
data truth, future accuracy, official sample eligibility or model certification.
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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from package_history_fixtures import evidence, revise
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_package_outcomes_pg import setup as outcome_setup
from test_package_outcomes_pg import verify as verify_outcome
from test_package_technical_eligibility_pg import frozen, submission_world
from test_package_technical_scope_pg import api as scope_api
from test_package_technical_scope_pg import exact, headers, requirements, uid
from test_package_technical_scope_pg import world as scope_world

from deploy.schema_plan import BASE_SQL
from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.runtime import Command, connection, etag, sha
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance import package_history_proofs as policy
from packages.rag.indexing import original_source_id
from packages.research import outcomes

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = "技术总分满分为20分，量尺为未加权原始分；聚合口径为官方公布的最终技术总分。"
EXTENSIONS = (
    "deploy/sql/model-governance.sql",
    "deploy/sql/package-historical-admission.sql",
    "deploy/sql/package-historical-research.sql",
)
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_HISTORY_PG") != "1",
    reason="fresh isolated package history cluster required",
)


@pytest.fixture(scope="module")
def database():
    admin_dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    name = "fusion_package_history_mechanism_" + uuid4().hex[:8]
    roles = {
        "api_dsn": (
            "fusion_package_requirements_service",
            ("tender_api", "tender_package_history_test_api"),
        ),
        "worker_dsn": ("fusion_package_requirements_worker", ("tender_worker",)),
        "verify_dsn": ("fusion_package_history_verifier", ("tender_package_history_verify",)),
        "train_dsn": ("fusion_package_history_trainer", ("tender_package_history_train",)),
        "evaluate_dsn": ("fusion_package_history_evaluator", ("tender_package_history_evaluate",)),
        "ordinary_api_dsn": ("fusion_package_history_ordinary_api", ("tender_api",)),
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_ENV_FILE", "explicit-package-history-tests")
        patch.setenv("APP_ORIGIN", "http://identity-v2.test")
        patch.setenv("SESSION_SECRET", uid())
        patch.setenv("CSRF_SECRET", uid())
        with psycopg.connect(admin_dsn, autocommit=True, row_factory=dict_row) as admin:
            assert admin.info.dbname == "postgres"
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
            )
            try:
                owner_dsn = make_conninfo(admin_dsn, dbname=name)
                with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
                    for path in (*BASE_SQL, *EXTENSIONS):
                        owner.execute((ROOT / path).read_text())
                    owner.execute(
                        "INSERT INTO package_historical_research.test_environments SELECT oid,datname,'dedicated_disposable_mechanism_database',clock_timestamp() FROM pg_database WHERE datname=current_database()"
                    )
                    values = {"owner": owner}
                    for key, (role, groups) in roles.items():
                        password = secrets.token_urlsafe(36)
                        admin.execute(
                            sql.SQL(
                                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                            ).format(sql.Identifier(role), sql.Literal(password))
                        )
                        for group in groups:
                            admin.execute(
                                sql.SQL("GRANT {} TO {}").format(
                                    sql.Identifier(group), sql.Identifier(role)
                                )
                            )
                        values[key] = make_conninfo(owner_dsn, user=role, password=password)
                    patch.setenv("API_DATABASE_DSN", values["api_dsn"])
                    yield values
            finally:
                admin.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(name)))
                for role, _ in roles.values():
                    admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


@pytest.fixture
def api(database):
    from apps.api.package_historical_research import router

    source = scope_api.__wrapped__(database)
    value = next(source)
    app = value["app"]
    previous = list(app.router.routes)
    # This fixture exercises the separately installed native two-SQL mechanism.
    # Production main mounts these same paths with the mandatory public bridge
    # dependency; the bridge suite tests those actual production routes. Remove
    # only this module's core routes so route order cannot accidentally select
    # a duplicate public path, then restore the complete application afterwards.
    app.router.routes[:] = [
        route
        for route in previous
        if getattr(getattr(route, "endpoint", None), "__module__", None)
        != "apps.api.package_historical_research"
    ]
    app.include_router(router)
    app.openapi_schema = None
    try:
        yield value
    finally:
        app.router.routes[:] = previous
        app.openapi_schema = None
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture
def world(api):
    w = scope_world.__wrapped__(api)
    with w["database"]["owner"].transaction():
        c = w["database"]["owner"]
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,79,'text',%s,%s)",
            (
                uid(),
                w["scope"].bid_id,
                w["member"].parse.parse_run_id,
                DECLARATION,
                sha(DECLARATION.encode()),
            ),
        )
        unique_text = "Synthetic independent case content " + uid()
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,80,'text',%s,%s)",
            (
                uid(),
                w["scope"].bid_id,
                w["member"].parse.parse_run_id,
                unique_text,
                sha(unique_text.encode()),
            ),
        )
        w["member"] = replace(
            w["member"],
            parse=read_parse_identity(
                c,
                w["scope"].bid_id,
                w["member"].document_version_id,
                w["member"].parse.parse_run_id,
            ),
        )
    return w


def subject(w, monkeypatch, *, value="0"):
    import test_package_outcomes_pg
    from test_package_technical_scope_pg import RAW

    saved, path = frozen(w)
    quote = f"Synthetic official final technical total: {value} points out of 20."
    monkeypatch.setattr(test_package_outcomes_pg, "QUOTE", quote)
    w = outcome_setup(submission_world(w, monkeypatch), with_authority=False)
    body = w["result_request"] | {"maximum": "20", "value": value}
    with connection() as c:
        result, head_tag = outcomes.register(
            c,
            actor=UUID(w["actor"]),
            bid=UUID(w["scope"].bid_id),
            body=body,
            command=None,
            previous=UUID(w["result"]["id"]),
            condition=w["result_headers"]["etag"],
        )
    w["result"] = result
    w["result_request"] = body
    w["result_headers"]["etag"] = head_tag
    w["result_headers"]["verification-etag"] = etag("outcome-verification", result["id"], 0)
    w["verification"]["evidence_refs"][0]["quote"] = quote
    verify_outcome(w)
    w.update(saved=saved, scope_path=path, originals={sha(RAW): RAW})
    raw = ("Synthetic official result " + w["source"]).encode()
    w["originals"][sha(raw)] = raw
    return w


def adapter(w):
    identity, key = uid(), Ed25519PrivateKey.generate()
    w["database"]["owner"].execute(
        "INSERT INTO package_historical_research.adapters(id,method,name,origin,public_key_hex,source_prefix,source_semantics,valid_from) VALUES(%s,'signed-source-evidence/1','Synthetic evidence adapter','synthetic',%s,'fixture://','Synthetic contemporaneous receipt assertions; no real historical truth','1970-01-01Z')",
        (identity, key.public_key().public_bytes_raw().hex()),
    )
    return identity, key


def material(w, adapter_id):
    with psycopg.connect(w["database"]["verify_dsn"], row_factory=dict_row) as c:
        return c.execute(
            "SELECT package_historical_research.verification_material(%s,%s,%s,%s) AS value",
            (w["saved"]["manifest"]["id"], w["submission"]["id"], w["result"]["id"], adapter_id),
        ).fetchone()["value"]


def ingest(w, envelope, adapter_id, tmp_path):
    profile, original = tmp_path / (uid() + ".profile"), tmp_path / (uid() + ".json")
    profile.write_text(
        "PACKAGE_HISTORY_VERIFY_DSN=" + shlex.quote(w["database"]["verify_dsn"]) + "\n"
    )
    original.write_text(json.dumps(envelope, ensure_ascii=False))
    profile.chmod(0o600)
    original.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "deploy/package_history_worker.py"),
            "--purpose",
            "verify",
            "--profile",
            str(profile),
            "--scope-id",
            w["saved"]["manifest"]["id"],
            "--submission-id",
            w["submission"]["id"],
            "--outcome-id",
            w["result"]["id"],
            "--adapter-id",
            adapter_id,
            "--evidence",
            str(original),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )  # nosec B603
    return result, json.loads(result.stdout) if result.stdout else None


def admit(w, proof_id):
    with connection() as c:
        command = Command(
            c,
            w["actor"],
            "package-history-admission",
            w["saved"]["manifest"]["id"],
            uid(),
            {"proof_id": proof_id},
        )
        value = c.execute(
            "SELECT package_historical_research.admit(%s,%s,%s) AS value",
            (proof_id, w["actor"], command.id),
        ).fetchone()["value"]
        command.finish(value, 201)
        return value


def test_actual_verifier_signature_native_zero_and_immutable_research_admission(
    exact, monkeypatch, tmp_path
):
    w = subject(exact, monkeypatch)
    identity, key = adapter(w)
    m = material(w, identity)
    assert m["context"]["label"]["value"] == "0"
    assert m["context"]["label"]["maximum"] == "20"
    envelope = evidence(m["context"], identity, key, w["originals"])
    verified = policy.verify(
        envelope,
        adapter=m["adapter"],
        context=m["context"],
        observed_at=envelope["payload"]["issued_at"],
    )
    assert verified["research_only"] and not verified["online_metrics_eligible"]
    result, receipt = ingest(w, envelope, identity, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    record = admit(w, receipt["result"]["proof_id"])
    assert record["official_technical_value"] == "0" and record["state"] == "mechanism_candidate"
    assert not record["formal_sample_created"] and not record["training_selected"]
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.samples WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 0
        )
        view = c.execute(
            "SELECT package_historical_research.admission_view(%s) AS value", (record["id"],)
        ).fetchone()["value"]
        assert view["current"] and view["admission"] == record


def qualified(w, monkeypatch, tmp_path, *, value="0", template_keys=()):
    w = subject(w, monkeypatch, value=value)
    identity, key = adapter(w)
    m = material(w, identity)
    envelope = evidence(m["context"], identity, key, w["originals"], template_keys=template_keys)
    result, receipt = ingest(w, envelope, identity, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    w["admission"] = admit(w, receipt["result"]["proof_id"])
    w.update(adapter_id=identity, signing_key=key, proof_envelope=envelope, proof_material=m)
    return w


def independent_case(api, tmp_path, *, value="0", template_keys=()):
    import test_package_technical_eligibility_pg as eligibility
    import test_package_technical_scope_pg as scopes

    with pytest.MonkeyPatch.context() as patch:
        raw = (
            b"%PDF-1.7\nSynthetic distinct historic original " + uuid4().hex.encode() + b"\n%%EOF\n"
        )
        patch.setattr(scopes, "RAW", raw)
        patch.setattr(eligibility, "RAW", raw)
        w = world.__wrapped__(api)
        w = requirements.__wrapped__(w)
        w = exact.__wrapped__(w, patch)
        return qualified(w, patch, tmp_path, value=value, template_keys=template_keys)


def registered_protocol(w):
    document = cpu.protocol(bootstrap_iterations=100)
    with connection() as c:
        command = Command(
            c, w["actor"], "package-history-protocol", w["actor"], uid(), {"document": document}
        )
        value = c.execute(
            "SELECT package_historical_research.register_protocol(%s,%s,%s) AS value",
            (Jsonb(document), w["actor"], command.id),
        ).fetchone()["value"]
        command.finish(value, 201)
        return value


def freeze_cohort(w, protocol, cases, boundary, *, cutoff=None, purposes=None):
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()
    purposes = purposes or ["fit", "fit", "development", "final", "final"]
    selected = [
        {"admission_id": case["admission"]["id"], "purpose": purpose}
        for case, purpose in zip(cases, purposes, strict=True)
    ]
    with connection() as c:
        command = Command(
            c,
            w["actor"],
            "package-history-cohort",
            protocol["id"],
            uid(),
            {"selections": selected, "boundary": boundary, "cutoff": cutoff},
        )
        result = c.execute(
            "SELECT package_historical_research.freeze_cohort(%s,%s,%s,%s,%s,%s) AS value",
            (protocol["id"], boundary, cutoff, Jsonb(selected), w["actor"], command.id),
        ).fetchone()["value"]
        command.finish(result, 201)
        return result


def job(w, cohort, kind):
    with connection() as c:
        command = Command(c, w["actor"], "package-history-job", cohort["id"], uid(), {"kind": kind})
        result = c.execute(
            "SELECT package_historical_research.start_job(%s,%s,%s,%s) AS value",
            (cohort["id"], kind, w["actor"], command.id),
        ).fetchone()["value"]
        command.finish(result, 201)
        return result


def cpu_child(w, task, tmp_path):
    purpose = task["kind"]
    profile = tmp_path / (uid() + ".profile")
    profile.write_text(
        "PACKAGE_HISTORY_"
        + purpose.upper()
        + "_DSN="
        + shlex.quote(w["database"][purpose + "_dsn"])
        + "\n"
    )
    profile.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "deploy/package_history_worker.py"),
            "--purpose",
            purpose,
            "--profile",
            str(profile),
            "--job-id",
            task["job_id"],
            "--generation",
            str(task["generation"]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )  # nosec B603
    return result, json.loads(result.stdout) if result.stdout else None


def cohort_fixture(api, tmp_path):
    cases = [independent_case(api, tmp_path, value=value) for value in ("0", "8", "7")]
    boundary = datetime.now(timezone.utc).isoformat()
    cases.extend(independent_case(api, tmp_path, value=value) for value in ("6", "9"))
    protocol = registered_protocol(cases[0])
    cohort = freeze_cohort(cases[0], protocol, cases, boundary)
    return cases, protocol, cohort, boundary


def test_actual_separate_cpu_training_evaluation_and_irreversible_final_exposure(api, tmp_path):
    cases, protocol, cohort, boundary = cohort_fixture(api, tmp_path)
    w = cases[0]
    trained = job(w, cohort, "train")
    result, receipt = cpu_child(w, trained, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    evaluated = job(w, cohort, "evaluate")
    result, receipt = cpu_child(w, evaluated, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    with connection() as c:
        view = c.execute(
            "SELECT package_historical_research.job_view(%s) AS value", (evaluated["job_id"],)
        ).fetchone()["value"]
        assert view["state"] == "succeeded" and view["current"]
        report = view["result"]
        assert report["report"]["denominator"] == 2 and report["report"]["counts"]["succeeded"] == 2
        assert report["research_only"] and report["acceptance_decision"] == "unavailable"
        assert report["timing"]["submission_split_at"] == cohort["timing"]["submission_split_at"]
    with pytest.raises(
        psycopg.errors.ObjectNotInPrerequisiteState, match="package_history_final_already_exposed"
    ):
        freeze_cohort(w, protocol, cases, boundary)
    # Read-only old report remains; no formal registry, model route or sample row.
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.samples WHERE bid_id=ANY(%s::uuid[])",
                ([case["scope"].bid_id for case in cases],),
            ).fetchone()["n"]
            == 0
        )


def sql_as(w, purpose, statement, args=()):
    with psycopg.connect(w["database"][purpose + "_dsn"], row_factory=dict_row) as c:
        row = c.execute(statement, args).fetchone()
        return row["value"] if row is not None and "value" in row else row


def claim(w, task, *, token=None, generation=None):
    return sql_as(
        w,
        task["kind"],
        "SELECT package_historical_research.claim_job(%s,%s,%s) AS value",
        (task["job_id"], generation or task["generation"], token or uid()),
    )


def lease_args(lease):
    return (lease["job_id"], lease["generation"], lease["fence"], lease["owner"])


def control_job(w, task, action):
    with connection() as c:
        cmd = Command(
            c,
            w["actor"],
            "package-history-job-control",
            task["job_id"],
            uid(),
            {"action": action, "generation": task["generation"]},
        )
        result = c.execute(
            "SELECT package_historical_research.control_job(%s,%s,%s,%s,%s) AS value",
            (task["job_id"], task["generation"], action, w["actor"], cmd.id),
        ).fetchone()["value"]
        cmd.finish(result, 200)
        return result


def test_actual_cpu_roles_cannot_read_proofs_context_originals_or_another_purpose(api, tmp_path):
    w = independent_case(api, tmp_path)
    targets = (w["saved"]["manifest"]["id"], w["submission"]["id"], w["result"]["id"])
    for purpose in ("train", "evaluate", "verify"):
        for table in (
            "design.outcomes",
            "design.evidence_blocks",
            "design.sessions",
            "package_historical_research.proofs",
            "package_historical_research.exports",
            "package_historical_research.adapters",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                sql_as(w, purpose, "SELECT * FROM " + table + " LIMIT 1")
    for purpose in ("train", "evaluate"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql_as(
                w,
                purpose,
                "SELECT package_historical_research.admission_context(%s,%s,%s)",
                targets,
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql_as(
                w,
                purpose,
                "SELECT package_historical_research.verification_material(%s,%s,%s,%s)",
                (*targets, w["adapter_id"]),
            )
    for purpose, forbidden in (
        ("train", "read_final"),
        ("evaluate", "read_training"),
        ("verify", "read_training"),
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql_as(
                w,
                purpose,
                f"SELECT package_historical_research.{forbidden}(%s,1,1,%s)",
                (uid(), uid()),
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql_as(
            w,
            "api",
            "SELECT package_historical_research.record_proof(%s,%s,%s,%s,%s,%s,%s)",
            (
                *targets,
                w["adapter_id"],
                Jsonb(w["proof_envelope"]),
                Jsonb({}),
                w["proof_material"]["context_digest"],
            ),
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="synthetic_environment_denied"):
        sql_as(
            w,
            "ordinary_api",
            "SELECT package_historical_research.admit(%s,%s,%s)",
            (w["admission"]["proof_id"], w["actor"], uid()),
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql_as(
            w,
            "api",
            "INSERT INTO package_historical_research.adapter_revocations(adapter_id,reason) VALUES(%s,'API cannot authorize/revoke evidence adapters') RETURNING adapter_id",
            (w["adapter_id"],),
        )


def test_fixed_verifier_rejects_authentic_but_late_or_missing_full_evidence_without_new_records(
    api, tmp_path
):
    w = independent_case(api, tmp_path)
    before = (
        w["database"]["owner"]
        .execute("SELECT count(*) AS n FROM package_historical_research.proofs")
        .fetchone()["n"]
    )
    for mutation in ("late", "visual", "unknown_aggregation", "signature"):
        changed = deepcopy(w["proof_envelope"])
        key = w["signing_key"]
        if mutation == "late":
            revise(
                changed,
                key,
                changed["payload"]["documents"][0]["exists"],
                lambda value, receipt=changed: value.update(
                    recorded_at=receipt["payload"]["issued_at"]
                ),
            )
        elif mutation == "visual":
            revise(
                changed,
                key,
                changed["payload"]["coverage_resource"],
                lambda value: value.update(pages=[]),
            )
        elif mutation == "unknown_aggregation":
            revise(
                changed,
                key,
                changed["payload"]["scale_resource"],
                lambda value: value.update(aggregation="unknown"),
            )
        else:
            changed["payload"]["receipt_id"] = "tampered"
        process, receipt = ingest(w, changed, w["adapter_id"], tmp_path)
        assert process.returncode == 2 and not receipt["ok"]
        assert receipt["paid_calls"] == 0 and receipt["provider_requests"] == 0
        assert receipt["code"] in {
            "PACKAGE_HISTORY_HISTORICAL_TIME_UNPROVEN",
            "PACKAGE_HISTORY_FULL_VISUAL_UNPROVEN",
            "PACKAGE_HISTORY_MAXIMUM_AGGREGATION_UNPROVEN",
            "PACKAGE_HISTORY_SIGNATURE_INVALID",
        }
    assert (
        w["database"]["owner"]
        .execute("SELECT count(*) AS n FROM package_historical_research.proofs")
        .fetchone()["n"]
        == before
    )


@pytest.mark.parametrize("change", ("bidder", "lot", "round"))
def test_actual_native_identity_change_does_not_requalify_frozen_proof(api, tmp_path, change):
    from packages.identity import repository as identities

    w = independent_case(api, tmp_path)
    identity = w["proof_material"]["context"]["identity"]
    with connection() as c:
        if change == "bidder":
            bidder = identities.register_bidder(
                c,
                UUID(w["actor"]),
                "Synthetic replacement bidder",
                "explicit identity change",
                None,
            )
            c.execute(
                "UPDATE design.bid_profiles SET bidder_id=%s WHERE bid_id=%s",
                (bidder["id"], w["scope"].bid_id),
            )
        else:
            lot_id = identity["lot_id"]
            if change == "lot":
                lot_id = identities.register_lot(
                    c,
                    UUID(w["actor"]),
                    {
                        "engineering_project_id": identity["engineering_project_id"],
                        "label": "Synthetic other lot",
                        "reason": "explicit lot change",
                    },
                    None,
                )["id"]
            round_id = identities.register_round(
                c,
                UUID(w["actor"]),
                {
                    "engineering_project_id": identity["engineering_project_id"],
                    "lot_id": lot_id,
                    "round_no": 2,
                    "reason": "explicit round change",
                },
                None,
            )["id"]
            c.execute(
                "UPDATE design.bid_profiles SET round_id=%s WHERE bid_id=%s",
                (round_id, w["scope"].bid_id),
            )
        identities.record_binding(
            c,
            UUID(w["scope"].bid_id),
            UUID(w["actor"]),
            None,
            reason="Synthetic exact identity correction",
            confirmed=True,
        )
    view = sql_as(
        w,
        "api",
        "SELECT package_historical_research.admission_view(%s) AS value",
        (w["admission"]["id"],),
    )
    assert not view["current"] and view["admission"] == w["admission"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="proof_stale"):
        admit(w, w["admission"]["proof_id"])


def test_committed_final_exposure_precedes_labels_and_invalidates_another_frozen_cohort(
    api, tmp_path
):
    cases, protocol, cohort, boundary = cohort_fixture(api, tmp_path)
    w = cases[0]
    another = freeze_cohort(w, protocol, cases, boundary)
    task = job(w, cohort, "train")
    assert cpu_child(w, task, tmp_path)[0].returncode == 0
    task = job(w, cohort, "evaluate")
    lease = claim(w, task)
    arguments = lease_args(lease)
    with pytest.raises(
        psycopg.errors.ObjectNotInPrerequisiteState, match="committed_exposure_required"
    ):
        sql_as(
            w, "evaluate", "SELECT package_historical_research.read_final(%s,%s,%s,%s)", arguments
        )
    with pytest.raises(
        psycopg.errors.ObjectNotInPrerequisiteState, match="committed_exposure_required"
    ):
        with psycopg.connect(w["database"]["evaluate_dsn"], row_factory=dict_row) as c:
            c.execute("SELECT package_historical_research.open_final(%s,%s,%s,%s)", arguments)
            c.execute("SELECT package_historical_research.read_final(%s,%s,%s,%s)", arguments)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM package_historical_research.exposures WHERE job_id=%s",
            (task["job_id"],),
        )
        .fetchone()["n"]
        == 0
    )
    exposure = sql_as(
        w,
        "evaluate",
        "SELECT package_historical_research.open_final(%s,%s,%s,%s) AS value",
        arguments,
    )
    bundle = sql_as(
        w,
        "evaluate",
        "SELECT package_historical_research.read_final(%s,%s,%s,%s) AS value",
        arguments,
    )
    assert {r["id"] for r in bundle["labels"]} == {
        cases[3]["admission"]["id"],
        cases[4]["admission"]["id"],
    }
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
        job(w, another, "train")
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="final_already_exposed"):
        freeze_cohort(w, protocol, cases, boundary)
    actual = (
        w["database"]["owner"]
        .execute("SELECT * FROM package_historical_research.exposures WHERE id=%s", (exposure,))
        .fetchone()
    )
    assert (
        actual["cohort_digest"] == cohort["digest"]
        and actual["membership_digest"] == cohort["membership_digest"]
    )
    assert actual["predictions_digest"] == bundle["predictions_digest"]
    assert {str(identity) for identity in actual["closure_ids"]} == {
        cases[3]["admission"]["id"],
        cases[4]["admission"]["id"],
    }


def test_owned_job_pause_recovery_fences_and_source_withdrawal_keep_old_results_read_only(
    api, tmp_path
):
    cases, protocol, cohort, boundary = cohort_fixture(api, tmp_path)
    w = cases[0]
    task = job(w, cohort, "train")
    stale = claim(w, task)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="job_not_claimable"):
        claim(w, task)
    training = sql_as(
        w,
        "train",
        "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value",
        lease_args(stale),
    )
    assert all(row["purpose"] != "final" for row in training["rows"])
    assert {row["id"] for row in training["rows"]}.isdisjoint(
        {case["admission"]["id"] for case in cases[3:]}
    )
    paused = control_job(w, task, "pause")
    resumed = control_job(w, paused, "resume")
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="lease_invalid"):
        sql_as(
            w,
            "train",
            "SELECT package_historical_research.read_training(%s,%s,%s,%s)",
            lease_args(stale),
        )
    assert cpu_child(w, resumed, tmp_path)[0].returncode == 0
    before = sql_as(
        w, "api", "SELECT package_historical_research.job_view(%s) AS value", (task["job_id"],)
    )
    assert before["state"] == "succeeded" and before["current"]
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(cases[-1]["source"])),),
        )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
        job(w, cohort, "evaluate")
    after = sql_as(
        w, "api", "SELECT package_historical_research.job_view(%s) AS value", (task["job_id"],)
    )
    assert (
        not after["current"]
        and after["result"] == before["result"]
        and after["state"] == "succeeded"
    )


def test_official_result_correction_invalidates_old_admission_without_rewriting_zero(api, tmp_path):
    w = independent_case(api, tmp_path)
    with connection() as c:
        result, _ = outcomes.register(
            c,
            actor=UUID(w["actor"]),
            bid=UUID(w["scope"].bid_id),
            body=w["result_request"] | {"value": "1"},
            command=None,
            previous=UUID(w["result"]["id"]),
            condition=w["result_headers"]["etag"],
        )
    assert result["id"] != w["result"]["id"]
    current = sql_as(
        w,
        "api",
        "SELECT package_historical_research.admission_view(%s) AS value",
        (w["admission"]["id"],),
    )
    assert not current["current"] and current["admission"]["official_technical_value"] == "0"
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="proof_stale"):
        admit(w, w["admission"]["proof_id"])


def validate_http(response, schema, status=200):
    from jsonschema import Draft202012Validator, FormatChecker

    from packages.contracts.package_historical_research_api import SCHEMAS

    assert response.status_code == status, response.json()
    assert {part.strip() for part in response.headers["cache-control"].split(",")} == {
        "private",
        "no-store",
    }
    Draft202012Validator(SCHEMAS[schema], format_checker=FormatChecker()).validate(response.json())
    return response.json()


def test_actual_http_zero_admission_etag_csrf_and_original_ack_after_source_withdrawal(
    exact, monkeypatch, tmp_path
):
    w = subject(exact, monkeypatch)
    path = w["scope_path"]
    params = {"submission_id": w["submission"]["id"], "outcome_id": w["result"]["id"]}
    missing = w["client"].get(path + "/historical-admission-context", params=params)
    value = validate_http(missing, "PackageHistoricalAdmissionContext")
    assert value["official_technical_value"] == "0" and value["proofs"] == []
    assert "PACKAGE_HISTORY_ORIGINAL_TIME_PROOF_MISSING" in {r["code"] for r in value["blockers"]}
    identity, key = adapter(w)
    material_value = material(w, identity)
    envelope = evidence(material_value["context"], identity, key, w["originals"])
    process, receipt = ingest(w, envelope, identity, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    current = w["client"].get(path + "/historical-admission-context", params=params)
    context = validate_http(current, "PackageHistoricalAdmissionContext")
    body = params | {
        "proof_id": receipt["result"]["proof_id"],
        "context_digest": context["context_digest"],
        "reason": "Explicit synthetic evidence-bound admission",
    }
    assert w["client"].post(path + "/historical-admissions", json=body).status_code == 403
    assert (
        w["client"].post(path + "/historical-admissions", json=body, headers=headers(w)).status_code
        == 428
    )
    assert (
        w["client"]
        .post(
            path + "/historical-admissions",
            json=body,
            headers=headers(w, etag=missing.headers["etag"]),
        )
        .status_code
        == 412
    )
    write_headers = headers(w, etag=current.headers["etag"])
    accepted = w["client"].post(path + "/historical-admissions", json=body, headers=write_headers)
    admission = validate_http(accepted, "PackageHistoricalAdmission", 201)
    assert admission["official_technical_value"] == "0" and not admission["training_selected"]
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (original_source_id(UUID(w["source"])),),
        )
    replay = w["client"].post(path + "/historical-admissions", json=body, headers=write_headers)
    assert replay.status_code == 201 and replay.headers["idempotency-replayed"] == "true"
    assert replay.json() == admission
    detail = validate_http(
        w["client"].get("/api/v1/package-historical-research/admissions/" + admission["id"]),
        "PackageHistoricalAdmissionView",
    )
    assert not detail["current"] and detail["admission"] == admission


def test_actual_http_closed_queries_reject_repeated_or_unknown_exact_ids(api):
    client = api["client"]
    ids = [uid() for _ in range(6)]
    path = (
        f"/api/v1/bids/{ids[0]}/packages/{ids[1]}/revisions/{ids[2]}"
        f"/technical-scopes/{ids[3]}/historical-admission-context"
    )
    params = [("submission_id", ids[4]), ("outcome_id", ids[5])]
    for extra in (
        ("submission_id", ids[4]),
        ("submission_id", uid()),
        ("outcome_id", ids[5]),
        ("outcome_id", uid()),
        ("latest", "true"),
        ("unexpected", ""),
    ):
        response = client.get(path, params=params + [extra])
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "PACKAGE_HISTORY_QUERY_INVALID"
    base = "/api/v1/package-historical-research"
    for suffix in (
        "/cpu-protocol-template",
        "/admissions/" + uid(),
        "/cohorts/" + uid(),
        "/jobs/" + uid(),
    ):
        for query in ([("scope_id", uid())], [("latest", "true"), ("latest", "false")]):
            response = client.get(base + suffix, params=query)
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "PACKAGE_HISTORY_QUERY_INVALID"


def test_base_only_actual_http_is_explicit_unavailable_without_optional_tables(database, tmp_path):
    name = "fusion_package_history_base_" + uuid4().hex[:8]
    admin_dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        try:
            with psycopg.connect(
                make_conninfo(admin_dsn, dbname=name), autocommit=True, row_factory=dict_row
            ) as owner:
                for source in BASE_SQL:
                    owner.execute((ROOT / source).read_text())
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
                        w = world.__wrapped__(client)
                        w = requirements.__wrapped__(w)
                        w = exact.__wrapped__(w, patch)
                        saved, path = frozen(w)
                        params = {"submission_id": uid(), "outcome_id": uid()}
                        context = validate_http(
                            w["client"].get(path + "/historical-admission-context", params=params),
                            "PackageHistoricalAdmissionContext",
                        )
                        assert (
                            not context["schema_configured"] and context["context_digest"] is None
                        )
                        assert context["official_technical_value"] is None
                        assert context["blockers"][0]["code"] == "PACKAGE_HISTORY_NOT_CONFIGURED"
                        template = validate_http(
                            w["client"].get(
                                "/api/v1/package-historical-research/cpu-protocol-template"
                            ),
                            "PackageHistoricalProtocolTemplate",
                        )
                        assert not template["schema_configured"]
                        unavailable = w["client"].post(
                            "/api/v1/package-historical-research/protocols",
                            json={
                                "method_digest": template["method_digest"],
                                "seed": 17,
                                "bootstrap_iterations": 100,
                                "reason": "Check unavailable deployment capability",
                            },
                            headers=headers(w),
                        )
                        assert (
                            unavailable.status_code == 503
                            and unavailable.json()["code"] == "PACKAGE_HISTORY_NOT_CONFIGURED"
                        )
                        assert (
                            owner.execute(
                                "SELECT to_regnamespace('package_historical_research') AS name"
                            ).fetchone()["name"]
                            is None
                        )
                    finally:
                        try:
                            next(stream)
                        except StopIteration:
                            pass
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(name)))


def test_full_registered_group_closure_includes_unselected_bridge_and_unknown_is_not_zero(
    api, tmp_path
):
    before = [independent_case(api, tmp_path, value=value) for value in ("0", "8", "7")]
    template_key = "synthetic-template-" + uid()
    bridge = independent_case(api, tmp_path, value="5", template_keys=(template_key,))
    boundary = datetime.now(timezone.utc).isoformat()
    final = independent_case(api, tmp_path, value="6")
    cutoff = datetime.now(timezone.utc).isoformat()
    crossing = independent_case(api, tmp_path, value="9", template_keys=(template_key,))
    unknown = independent_case(api, tmp_path, value="0")
    cases = before + [final, crossing, unknown]
    w = before[0]
    protocol = registered_protocol(w)
    cohort = freeze_cohort(
        w,
        protocol,
        cases,
        boundary,
        cutoff=cutoff,
        purposes=["fit", "fit", "development", "final", "final", "final"],
    )
    selected = {m["admission_id"]: m for m in cohort["members"]}
    excluded = selected[crossing["admission"]["id"]]
    assert (
        excluded["purpose"] == "excluded"
        and excluded["exclusion_reason"] == "group_spans_submission_split"
    )
    assert bridge["admission"]["id"] in excluded["closure_ids"]
    assert (
        selected[unknown["admission"]["id"]]["exclusion_reason"] == "label_after_available_cutoff"
    )
    trained = job(w, cohort, "train")
    assert cpu_child(w, trained, tmp_path)[0].returncode == 0
    evaluated = job(w, cohort, "evaluate")
    assert cpu_child(w, evaluated, tmp_path)[0].returncode == 0
    view = sql_as(
        w, "api", "SELECT package_historical_research.job_view(%s) AS value", (evaluated["job_id"],)
    )
    report = view["result"]["report"]
    assert report["denominator"] == 3 and report["counts"] == {
        "succeeded": 1,
        "failed": 0,
        "rejected": 1,
        "unlabeled": 1,
    }
    labels = (
        w["database"]["owner"]
        .execute(
            "SELECT document FROM package_historical_research.exports WHERE cohort_id=%s AND purpose='final_labels'",
            (cohort["id"],),
        )
        .fetchone()["document"]
    )
    assert next(row for row in labels if row["id"] == unknown["admission"]["id"])["target"] is None
    exposed = (
        w["database"]["owner"]
        .execute(
            "SELECT m.identity FROM package_historical_research.exposure_members m JOIN package_historical_research.exposures x ON x.id=m.exposure_id WHERE x.job_id=%s AND m.kind='admission'",
            (evaluated["job_id"],),
        )
        .fetchall()
    )
    assert bridge["admission"]["id"] in {row["identity"] for row in exposed}


def test_new_bridge_and_operator_source_revocation_invalidate_frozen_membership(api, tmp_path):
    left, right = "template-" + uid(), "template-" + uid()
    cases = [
        independent_case(api, tmp_path, value="0", template_keys=(left,)),
        independent_case(api, tmp_path, value="8"),
        independent_case(api, tmp_path, value="7"),
    ]
    boundary = datetime.now(timezone.utc).isoformat()
    cases += [
        independent_case(api, tmp_path, value="6", template_keys=(right,)),
        independent_case(api, tmp_path, value="9"),
    ]
    w = cases[0]
    protocol = registered_protocol(w)
    cohort = freeze_cohort(w, protocol, cases, boundary)
    independent_case(api, tmp_path, value="2", template_keys=(left, right))
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="cohort_stale"):
        job(w, cohort, "train")
    w["database"]["owner"].execute(
        "INSERT INTO package_historical_research.adapter_revocations(adapter_id,reason) VALUES(%s,'Synthetic operator revocation; no business grant')",
        (cases[1]["adapter_id"],),
    )
    detail = sql_as(
        w,
        "api",
        "SELECT package_historical_research.admission_view(%s) AS value",
        (cases[1]["admission"]["id"],),
    )
    assert not detail["current"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="proof_stale"):
        admit(cases[1], cases[1]["admission"]["proof_id"])


def test_actual_http_protocol_cohort_job_control_and_closed_output_fixture(api, tmp_path):
    cases, _, _, boundary = cohort_fixture(api, tmp_path)
    w = cases[0]
    base = "/api/v1/package-historical-research"
    template_response = w["client"].get(base + "/cpu-protocol-template")
    template = validate_http(template_response, "PackageHistoricalProtocolTemplate")
    assert template["schema_configured"] and not template["feature_calibration_available"]
    protocol_request = {
        "method_digest": template["method_digest"],
        "seed": 17,
        "bootstrap_iterations": 100,
        "reason": "Explicit frozen constant baseline research method",
    }
    protocol_response = w["client"].post(
        base + "/protocols", json=protocol_request, headers=headers(w)
    )
    protocol = validate_http(protocol_response, "PackageHistoricalProtocol", 201)
    cohort_request = {
        "protocol_id": protocol["id"],
        "submission_split_at": boundary,
        "label_available_as_of": datetime.now(timezone.utc).isoformat(),
        "selections": [
            {"admission_id": case["admission"]["id"], "purpose": purpose}
            for case, purpose in zip(
                cases, ("fit", "fit", "development", "final", "final"), strict=True
            )
        ],
        "reason": "Explicit independent source groups and actual retrospective cutoffs",
    }
    cohort_response = w["client"].post(base + "/cohorts", json=cohort_request, headers=headers(w))
    cohort = validate_http(cohort_response, "PackageHistoricalCohort", 201)
    current_response = w["client"].get(base + "/cohorts/" + cohort["id"])
    current = validate_http(current_response, "PackageHistoricalCohortView")
    assert current["current"]
    start_request = {"kind": "train", "reason": "Run actual isolated zero-provider CPU baseline"}
    task_response = w["client"].post(
        base + "/cohorts/" + cohort["id"] + "/jobs",
        json=start_request,
        headers=headers(w, etag=current_response.headers["etag"]),
    )
    task = validate_http(task_response, "PackageHistoricalJob", 201)
    task_path = base + "/jobs/" + task["job_id"]
    queued_response = w["client"].get(task_path)
    queued = validate_http(queued_response, "PackageHistoricalJobView")
    pause_body = {
        "action": "pause",
        "generation": task["generation"],
        "reason": "Exercise recoverable task command",
    }
    pause_headers = headers(w, etag=queued_response.headers["etag"])
    paused_response = w["client"].post(
        task_path + "/control", json=pause_body, headers=pause_headers
    )
    paused = validate_http(paused_response, "PackageHistoricalJob", 200)
    assert paused["generation"] == task["generation"] + 1
    repeated = w["client"].post(task_path + "/control", json=pause_body, headers=pause_headers)
    assert (
        repeated.status_code == 200
        and repeated.headers["idempotency-replayed"] == "true"
        and repeated.json() == paused
    )
    paused_view = w["client"].get(task_path)
    resumed_response = w["client"].post(
        task_path + "/control",
        json={
            "action": "resume",
            "generation": paused["generation"],
            "reason": "Resume same owned CPU task",
        },
        headers=headers(w, etag=paused_view.headers["etag"]),
    )
    resumed = validate_http(resumed_response, "PackageHistoricalJob", 200)
    process, receipt = cpu_child(w, resumed, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    trained_response = w["client"].get(task_path)
    trained = validate_http(trained_response, "PackageHistoricalJobView")
    assert trained["state"] == "succeeded"
    current_response = w["client"].get(base + "/cohorts/" + cohort["id"])
    evaluated_response = w["client"].post(
        base + "/cohorts/" + cohort["id"] + "/jobs",
        json={
            "kind": "evaluate",
            "reason": "Expose once, then independently evaluate sealed predictions",
        },
        headers=headers(w, etag=current_response.headers["etag"]),
    )
    evaluated = validate_http(evaluated_response, "PackageHistoricalJob", 201)
    process, receipt = cpu_child(w, evaluated, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    result_response = w["client"].get(base + "/jobs/" + evaluated["job_id"])
    final = validate_http(result_response, "PackageHistoricalJobView")
    saved_response = w["client"].get(
        w["scope_path"] + "/historical-admission-context",
        params={"submission_id": w["submission"]["id"], "outcome_id": w["result"]["id"]},
    )
    admission_context = validate_http(saved_response, "PackageHistoricalAdmissionContext")
    fixture = {
        "synthetic": True,
        "real_qualification": False,
        "paid_calls": 0,
        "provider_requests": 0,
        "transport": "actual FastAPI ASGI and PostgreSQL 17 nonowner roles; fixed private CPU processes",
        "scope_path": w["scope_path"],
        "admission_context": admission_context,
        "admission_context_etag": saved_response.headers["etag"],
        "admission": w["admission"],
        "protocol_request": protocol_request,
        "protocol": protocol,
        "cohort_request": cohort_request,
        "cohort": cohort,
        "cohort_view": current,
        "queued_job": queued,
        "paused_job": paused,
        "resumed_job": resumed,
        "training_job": trained,
        "evaluation_job": final,
    }
    destination = Path("/tmp/tender-review-current/package-historical-research-http.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")


def test_lease_reclaim_after_actual_expiry_fences_old_publisher_and_completed_worker_replays(
    api, tmp_path
):
    cases, _, cohort, _ = cohort_fixture(api, tmp_path)
    w = cases[0]
    task = job(w, cohort, "train")
    stale = claim(w, task)
    exported = sql_as(
        w,
        "train",
        "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value",
        lease_args(stale),
    )
    output = cpu.train(exported)
    started = time.monotonic()
    deadline = started + 140
    recovered = None
    while time.monotonic() < deadline:
        try:
            recovered = claim(w, task)
            break
        except psycopg.errors.ObjectNotInPrerequisiteState as error:
            assert error.diag.message_primary == "package_history_job_not_claimable"
            Event().wait(5)
    assert recovered is not None and time.monotonic() - started >= 110
    assert (
        recovered["fence"] == stale["fence"] + 1 and recovered["generation"] == stale["generation"]
    )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="lease_invalid"):
        sql_as(
            w,
            "train",
            "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s)",
            (*lease_args(stale), Jsonb(output), policy.digest(output)),
        )
    sql_as(
        w,
        "train",
        "SELECT package_historical_research.renew_job(%s,%s,%s,%s)",
        lease_args(recovered),
    )
    sql_as(
        w,
        "train",
        "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s)",
        (*lease_args(recovered), Jsonb(output), policy.digest(output)),
    )
    process, receipt = cpu_child(w, task, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert receipt["result"]["state"] == "succeeded" and receipt["result"][
        "result_digest"
    ] == policy.digest(output)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM package_historical_research.results WHERE job_id=%s",
            (task["job_id"],),
        )
        .fetchone()["n"]
        == 1
    )
