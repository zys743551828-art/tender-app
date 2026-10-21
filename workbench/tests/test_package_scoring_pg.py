"""Native isolated package jobs, actual roles/ledger and zero-network transport.

All originals, authoritative clauses and provider envelopes are synthetic. This
suite explicitly cannot establish formal, historical, metrics or model eligibility.
"""
# ruff: noqa: F401,F811

import json
import os
import secrets
import shlex
import subprocess  # nosec B404 -- fixed purpose child
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_package_technical_eligibility_pg import frozen
from test_package_technical_scope_pg import api, exact, requirements, uid, world

from deploy.schema_plan import BASE_SQL
from packages.domain.runtime import Command, connection, sha
from packages.model_governance import package_scoring_profile as method

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_SCORE_PG") != "1",
    reason="separate disposable package-score DB explicitly required",
)
EXTENSIONS = (
    "deploy/sql/model-governance.sql",
    "deploy/sql/historical-backtest.sql",
    "deploy/sql/historical-input-qualification.sql",
    "deploy/sql/model-governance-release.sql",
    "deploy/sql/score-execution.sql",
    "deploy/sql/package-score-execution.sql",
)


@pytest.fixture(scope="module")
def database():
    admin_dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    name = "fusion_package_score_mechanism_" + uuid4().hex[:8]
    roles = {
        "api_dsn": (
            "fusion_package_requirements_service",
            ("tender_api", "tender_package_score_test_api"),
        ),
        "worker_dsn": ("fusion_package_requirements_worker", ("tender_worker",)),
        "score_dsn": ("fusion_package_score_worker", ("tender_package_score_test_worker",)),
        "ordinary_api_dsn": ("fusion_package_score_ordinary_api", ("tender_api",)),
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_ENV_FILE", "explicit-package-score-tests")
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
                        "INSERT INTO package_score_execution.test_environments(database_oid,database_name,isolation) SELECT oid,datname,'dedicated_disposable_mechanism_database' FROM pg_database WHERE datname=current_database()"
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


def prices():
    return {
        "profile_digest": method.digest(),
        "currency": "USD",
        "context_tokens": 1_000_000,
        "max_output_tokens": 4096,
        "input_per_million": "0.01",
        "output_per_million": "0.02",
    }


def prepare(w, *, grant=True, saved=None):
    saved = saved or frozen(w)[0]
    scope_id = saved["manifest"]["id"]
    if grant:
        w["database"]["owner"].execute(
            "INSERT INTO package_score_execution.test_authorities(scope_id,database_oid,scope_digest,method_digest,scope_method_digest,origin,valid_until) SELECT %s,oid,%s,%s,%s,'synthetic',clock_timestamp()+interval '1 hour' FROM pg_database WHERE datname=current_database() ON CONFLICT DO NOTHING",
            (
                scope_id,
                saved["digest"],
                method.digest(),
                saved["manifest"]["preview"]["manifest"]["method"]["digest"],
            ),
        )
    with connection() as c:
        command = Command(
            c,
            w["actor"],
            "package-score-mechanism-input",
            scope_id,
            uid(),
            {"scope_digest": saved["digest"], "prices": prices()},
        )
        identity = c.execute(
            "SELECT package_score_execution.create_input(%s,%s,%s,%s,%s) AS value",
            (scope_id, saved["digest"], Jsonb(prices()), w["actor"], command.id),
        ).fetchone()["value"]
        command.finish({"input_id": str(identity)}, 201)
    return saved, str(identity)


def start(w, identity, budget="1"):
    with connection() as c:
        command = Command(
            c, w["actor"], "package-score-mechanism-job", identity, uid(), {"budget": budget}
        )
        job = c.execute(
            "SELECT package_score_execution.start_job(%s,%s,%s,%s) AS value",
            (identity, budget, w["actor"], command.id),
        ).fetchone()["value"]
        command.finish({"job_id": str(job)}, 201)
    return str(job)


def view(job):
    with connection() as c:
        return c.execute("SELECT package_score_execution.job_view(%s) AS value", (job,)).fetchone()[
            "value"
        ]


def packets(w, identity):
    # Only synthetic expected-envelope preparation uses owner inspection. The
    # executing child can access solely the owned input RPC with a live fence.
    return [
        row["raw_content"]
        for row in w["database"]["owner"]
        .execute(
            "SELECT raw_content::jsonb AS raw_content FROM package_score_execution.input_packages(%s) ORDER BY rule_id",
            (identity,),
        )
        .fetchall()
    ]


def response(packet):
    citations = []
    for part_id in packet["required_part_ids"]:
        part = next(row for row in packet["parts"] if row["part"]["part_id"] == part_id)
        document = next(
            row
            for row in packet["documents"]
            if row["package_role"] == "target"
            and row["document_version_id"] == part["document_version_id"]
        )
        block = next(row for row in document["blocks"] if row["id"] in part["block_ids"])
        citations.append(
            {
                "document_version_id": document["document_version_id"],
                "parse_id": document["parse"]["parse_run_id"],
                "physical_page": block["physical_page"],
                "evidence_id": block["id"],
                "quote": block["text_content"],
            }
        )
    return {
        "band_id": packet["rule"]["bands"][0]["id"],
        "reason": "Synthetic transport response for complete supplied test ranges only.",
        "coverage": "complete",
        "status": "valid",
        "covered_part_ids": packet["required_part_ids"],
        "evidence": citations,
    }


def http_fixture(w, identity, path, *, invalid=False):
    entries = []
    for packet in packets(w, identity):
        request = method.request_for(packet)
        # This is the exact existing DeepSeek adapter's provider HTTP shape.
        messages = [
            {
                "role": "system",
                "content": "Return only one valid JSON object satisfying this JSON Schema: "
                + json.dumps(request["json_schema"], ensure_ascii=False),
            }
        ] + request["messages"]
        body = {
            "model": "deepseek-flash",
            "messages": messages,
            "max_tokens": request["max_tokens"],
            "temperature": request["temperature"],
            "thinking": {"type": "disabled"},
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        for _ in range(3):
            data = response(packet)
            if invalid:
                data["status"] = "unable_to_judge"
            entries.append(
                {
                    "request_digest": sha(body),
                    "response": {
                        "id": "synthetic-" + uid(),
                        "model": "deepseek-flash",
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 30,
                            "total_tokens": 130,
                        },
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": json.dumps(data)},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                }
            )
    path.write_text(
        json.dumps(
            {"schema": "package-score-http-fixture/1", "synthetic": True, "responses": entries}
        )
    )
    return entries


def child(w, job, identity, tmp_path, *, generation=1, invalid=False, fixture=True):
    profile = tmp_path / (uid() + ".env")
    profile.write_text(
        "PACKAGE_SCORE_DATABASE_DSN=" + shlex.quote(w["database"]["score_dsn"]) + "\n"
    )
    profile.chmod(0o600)
    command = [
        sys.executable,
        "-I",
        str(ROOT / "deploy/package_scoring_worker.py"),
        "--profile",
        str(profile),
        "--job-id",
        str(job),
        "--generation",
        str(generation),
    ]
    if fixture:
        source = tmp_path / (uid() + ".json")
        http_fixture(w, identity, source, invalid=invalid)
        command += ["--mechanism-response-fixture", str(source)]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False
    )  # nosec B603 -- fixed owned local child
    assert result.stdout.strip(), result.stderr
    value = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == (0 if value["ok"] else 2), result.stderr
    return value


def worker(w, query, params=()):
    with psycopg.connect(w["database"]["score_dsn"], row_factory=dict_row) as c:
        return c.execute(query, params).fetchone()["value"]


def claim(w, job, generation=1):
    return worker(
        w, "SELECT package_score_execution.claim_job(%s,%s,%s) AS value", (job, generation, uuid4())
    )


def lease_args(lease):
    return lease["job_id"], lease["generation"], lease["fence"], lease["owner"]


def test_actual_worker_complete_three_same_inputs_and_isolated_results(exact, tmp_path):
    saved, identity = prepare(exact)
    job = start(exact, identity)
    output = child(exact, job, identity, tmp_path)
    assert output["ok"] and output["mock_http_calls"] == 6 and output["paid_calls"] == 0
    read = view(job)
    assert read["state"] == "succeeded" and Decimal(read["reserved_fee"]) == 0
    assert Decimal(read["estimated_fee"]) > 0 and read["calls"] == [
        {"state": "succeeded", "count": 6}
    ]
    document = read["result"]["document"]
    assert (
        document["scope_id"] == saved["manifest"]["id"]
        and document["scope_digest"] == saved["digest"]
    )
    assert len(document["items"]) == 2 and all(
        row["valid_replicates"] == 3 for row in document["items"]
    )
    assert document["numeric_prediction"] is None
    assert not any(
        document[k] for k in ("formal_scoring_eligible", "training_eligible", "metrics_eligible")
    )
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM score_execution.results WHERE job_id=%s", (job,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.samples WHERE bid_id=%s", (exact["scope"].bid_id,)
            ).fetchone()["n"]
            == 0
        )
        rows = c.execute(
            "SELECT chapter_digest,count(DISTINCT request_digest) AS requests,count(DISTINCT id) AS calls,array_agg(replicate ORDER BY replicate) AS replicates FROM score_execution.calls WHERE job_id=%s GROUP BY chapter_digest",
            (job,),
        ).fetchall()
        assert all(
            row["requests"] == 1 and row["calls"] == 3 and row["replicates"] == [1, 2, 3]
            for row in rows
        )


def test_owner_only_scope_authority_and_ordinary_roles_cannot_qualify(exact):
    saved = frozen(exact)[0]
    with pytest.raises(psycopg.Error) as error:
        prepare(exact, grant=False, saved=saved)
    assert error.value.sqlstate == "55000"
    for key in ("api_dsn", "ordinary_api_dsn", "worker_dsn", "score_dsn"):
        with psycopg.connect(exact["database"][key]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(
                    "INSERT INTO package_score_execution.test_authorities(scope_id) VALUES(%s)",
                    (saved["manifest"]["id"],),
                )


def test_actual_worker_has_no_raw_source_label_ledger_or_other_purpose_reads(exact):
    for query in (
        "SELECT * FROM design.outcomes",
        "SELECT * FROM design.bid_package_technical_scopes",
        "SELECT * FROM score_execution.calls",
        "SELECT * FROM package_score_execution.test_authorities",
        "SELECT score_execution.claim_job(NULL,1,NULL)",
    ):
        with psycopg.connect(exact["database"]["score_dsn"]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(query)


def test_unconfigured_transport_fails_before_claim_or_reservation(exact, tmp_path):
    _, identity = prepare(exact)
    job = start(exact, identity)
    output = child(exact, job, identity, tmp_path, fixture=False)
    assert output["code"] == "PACKAGE_SCORE_PROVIDER_UNQUALIFIED" and output["mock_http_calls"] == 0
    assert view(job)["state"] == "queued" and view(job)["calls"] == []


def test_budget_ceiling_checked_before_job_or_model_call(exact):
    _, identity = prepare(exact)
    with pytest.raises(psycopg.Error) as error:
        start(exact, identity, "0.00001")
    assert error.value.sqlstate == "22023"
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM score_execution.jobs WHERE input_id=%s", (identity,)
            ).fetchone()["n"]
            == 0
        )


def test_invalid_billed_answer_is_not_a_valid_replicate_and_is_not_resent(exact, tmp_path):
    _, identity = prepare(exact)
    job = start(exact, identity)
    output = child(exact, job, identity, tmp_path, invalid=True)
    assert not output["ok"] and output["mock_http_calls"] == 1
    read = view(job)
    assert read["state"] == "paused" and read["result"] is None
    assert (
        read["calls"] == [{"state": "succeeded", "count": 1}] and Decimal(read["estimated_fee"]) > 0
    )
    with connection() as c:
        generation = c.execute(
            "SELECT package_score_execution.change_job(%s,%s,'resume',%s,'resume exact recorded execution') AS value",
            (job, read["generation"], exact["actor"]),
        ).fetchone()["value"]
    replay = child(exact, job, identity, tmp_path, generation=generation)
    assert not replay["ok"] and replay["mock_http_calls"] == 0
    assert view(job)["result"] is None


def test_success_recovery_reuses_original_calls_without_sending(exact, tmp_path):
    saved, identity = prepare(exact)
    job = start(exact, identity)
    assert child(exact, job, identity, tmp_path)["ok"]
    _, next_input = prepare(exact, saved=saved)
    next_job = start(exact, next_input)
    output = child(exact, next_job, next_input, tmp_path)
    assert output["ok"] and output["mock_http_calls"] == 0
    read = view(next_job)
    assert read["reused_calls"] == 6 and Decimal(read["estimated_fee"]) == 0


@pytest.mark.parametrize("state", ["unknown", "not_sent"])
def test_unresolved_logical_call_blocks_resume_and_new_nonce(exact, state):
    saved, identity = prepare(exact)
    job = start(exact, identity)
    lease = claim(exact, job)
    owned = worker(
        exact, "SELECT package_score_execution.owned_input(%s,%s,%s,%s) AS value", lease_args(lease)
    )
    unit = owned["chapters"][0]
    reserved = worker(
        exact,
        "SELECT package_score_execution.reserve_call(%s,%s,%s,%s,%s,1,%s,%s,%s) AS value",
        (
            *lease_args(lease),
            unit["id"],
            sha(method.request_for(unit["package"])),
            method.digest(),
            str(method.conservative_fee(prices())),
        ),
    )
    worker(
        exact,
        "SELECT package_score_execution.settle_call(%s,%s,%s,NULL,%s) AS value",
        (reserved["call_id"], lease["owner"], state, "0" if state == "not_sent" else None),
    )
    read = view(job)
    assert read["state"] == "paused" and (Decimal(read["reserved_fee"]) > 0) == (state == "unknown")
    with pytest.raises(psycopg.Error) as error, connection() as c:
        c.execute(
            "SELECT package_score_execution.change_job(%s,1,'resume',%s,'no duplicate attempt')",
            (job, exact["actor"]),
        )
    assert error.value.sqlstate == "55000"
    _, other_input = prepare(exact, saved=saved)
    with pytest.raises(psycopg.Error) as error:
        start(exact, other_input)
    assert error.value.sqlstate == "55000"


def test_new_generation_rejects_old_lease_before_any_provider_call(exact):
    _, identity = prepare(exact)
    job = start(exact, identity)
    old = claim(exact, job)
    with connection() as c:
        c.execute(
            "SELECT package_score_execution.change_job(%s,1,'pause',%s,'explicit operator pause')",
            (job, exact["actor"]),
        )
        generation = c.execute(
            "SELECT package_score_execution.change_job(%s,2,'resume',%s,'explicit resume') AS value",
            (job, exact["actor"]),
        ).fetchone()["value"]
    new = claim(exact, job, generation)
    assert new["fence"] > old["fence"]
    with pytest.raises(psycopg.Error) as error:
        worker(
            exact,
            "SELECT package_score_execution.owned_input(%s,%s,%s,%s) AS value",
            lease_args(old),
        )
    assert error.value.sqlstate == "55000"


def record_before_publish(w, identity, job):
    lease = claim(w, job)
    owned = worker(
        w, "SELECT package_score_execution.owned_input(%s,%s,%s,%s) AS value", lease_args(lease)
    )
    items = []
    for unit in owned["chapters"]:
        packet = unit["package"]
        request_digest = sha(method.request_for(packet))
        judgments = []
        for replicate in (1, 2, 3):
            reserved = worker(
                w,
                "SELECT package_score_execution.reserve_call(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS value",
                (
                    *lease_args(lease),
                    unit["id"],
                    replicate,
                    request_digest,
                    method.digest(),
                    str(method.conservative_fee(prices())),
                ),
            )
            data = response(packet)
            raw = {
                "schema": "controlled-score-response/1",
                "execution_purpose": "score",
                "data": data,
                "content": json.dumps(data),
                "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                "model": "deepseek-flash",
                "request_id": "synthetic-" + uid(),
                "response_id": "synthetic-" + uid(),
                "finish_reason": "stop",
                "request_digest": request_digest,
                "profile_digest": method.digest(),
                "formal_scoring_eligible": False,
                "fee_basis": "usage_price_estimate",
            }
            worker(
                w,
                "SELECT package_score_execution.settle_call(%s,%s,'succeeded',%s,%s) AS value",
                (reserved["call_id"], lease["owner"], json.dumps(raw), "0.0000016"),
            )
            judgments.append(
                {"replicate": replicate, "call_id": str(reserved["call_id"]), "payload": data}
            )
        items.append(
            {
                "rule_id": packet["rule"]["id"],
                "package_digest": packet["digest"],
                "valid_replicates": 3,
                "judgments": judgments,
            }
        )
    value = {
        "schema": "package-technical-judgments/1",
        "execution_purpose": "package_technical_judgment",
        "execution_mode": "mechanism_test",
        "scope_id": owned["scope_id"],
        "scope_digest": owned["scope_digest"],
        "input_digest": owned["input_digest"],
        "method_digest": method.digest(),
        "provider": "deepseek",
        "model_alias": "deepseek-flash",
        "items": items,
        "numeric_prediction": None,
        "formal_scoring_eligible": False,
        "training_eligible": False,
        "metrics_eligible": False,
        "eligibility_reasons": ["isolated_synthetic_mechanism_only"],
    }
    return lease, value


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(formal_scoring_eligible=True),
        lambda value: value.update(metrics_eligible=True, training_eligible=True),
        lambda value: value.update(scope_digest="0" * 64),
        lambda value: value["items"].pop(),
        lambda value: value["items"][0]["judgments"].pop(),
        lambda value: value["items"][0]["judgments"].__setitem__(
            1, deepcopy(value["items"][0]["judgments"][0])
        ),
        lambda value: value["items"][0]["judgments"][0]["payload"]["evidence"][0].update(
            quote="not in frozen evidence"
        ),
    ],
)
def test_native_publication_rejects_forged_eligibility_wrong_scope_partial_or_duplicate_judgments(
    exact, mutation
):
    _, identity = prepare(exact)
    job = start(exact, identity)
    lease, value = record_before_publish(exact, identity, job)
    mutation(value)
    with pytest.raises(psycopg.Error) as error:
        worker(
            exact,
            "SELECT package_score_execution.publish_result(%s,%s,%s,%s,%s) AS value",
            (*lease_args(lease), Jsonb(value)),
        )
    assert error.value.sqlstate == "23514"
    assert view(job)["result"] is None


def test_arbitrary_request_digest_cannot_reserve_a_valid_packet(exact):
    _, identity = prepare(exact)
    job = start(exact, identity)
    lease = claim(exact, job)
    owned = worker(
        exact, "SELECT package_score_execution.owned_input(%s,%s,%s,%s) AS value", lease_args(lease)
    )
    with pytest.raises(psycopg.Error) as error:
        worker(
            exact,
            "SELECT package_score_execution.reserve_call(%s,%s,%s,%s,%s,1,%s,%s,%s) AS value",
            (
                *lease_args(lease),
                owned["chapters"][0]["id"],
                "0" * 64,
                method.digest(),
                str(method.conservative_fee(prices())),
            ),
        )
    assert error.value.sqlstate == "23514"
    assert view(job)["calls"] == [] and Decimal(view(job)["reserved_fee"]) == 0


def test_source_withdrawal_after_reservation_settles_actual_usage_but_cannot_publish(exact):
    _, identity = prepare(exact)
    job = start(exact, identity)
    lease, value = record_before_publish(exact, identity, job)
    packet = packets(exact, identity)[0]
    source_id = packet["source_snapshot"][0]["ancestor_id"]
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (source_id,),
        )
    assert not view(job)["source_current"]
    with pytest.raises(psycopg.Error) as error:
        worker(
            exact,
            "SELECT package_score_execution.publish_result(%s,%s,%s,%s,%s) AS value",
            (*lease_args(lease), Jsonb(value)),
        )
    assert error.value.sqlstate == "55000" and view(job)["result"] is None
    assert Decimal(view(job)["estimated_fee"]) > 0


def test_settlement_after_lease_expiry_and_source_withdrawal_preserves_real_usage(exact):
    _, identity = prepare(exact)
    job = start(exact, identity)
    lease = claim(exact, job)
    owned = worker(
        exact, "SELECT package_score_execution.owned_input(%s,%s,%s,%s) AS value", lease_args(lease)
    )
    unit = owned["chapters"][0]
    packet = unit["package"]
    request_digest = sha(method.request_for(packet))
    reserved = worker(
        exact,
        "SELECT package_score_execution.reserve_call(%s,%s,%s,%s,%s,1,%s,%s,%s) AS value",
        (
            *lease_args(lease),
            unit["id"],
            request_digest,
            method.digest(),
            str(method.conservative_fee(prices())),
        ),
    )
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (packet["source_snapshot"][0]["ancestor_id"],),
        )
    exact["database"]["owner"].execute(
        "UPDATE score_execution.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
        (job,),
    )
    data = response(packet)
    raw = {
        "schema": "controlled-score-response/1",
        "execution_purpose": "score",
        "data": data,
        "content": json.dumps(data),
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        "model": "deepseek-flash",
        "request_id": "synthetic-" + uid(),
        "response_id": "synthetic-" + uid(),
        "finish_reason": "stop",
        "request_digest": request_digest,
        "profile_digest": method.digest(),
        "formal_scoring_eligible": False,
        "fee_basis": "usage_price_estimate",
    }
    worker(
        exact,
        "SELECT package_score_execution.settle_call(%s,%s,'succeeded',%s,%s) AS value",
        (reserved["call_id"], lease["owner"], json.dumps(raw), "0.0000016"),
    )
    read = view(job)
    assert (
        not read["source_current"]
        and Decimal(read["reserved_fee"]) == 0
        and Decimal(read["estimated_fee"]) == Decimal("0.0000016")
    )
    assert read["result"] is None


def test_public_formal_api_does_not_borrow_owner_registered_mechanism_authority(exact):
    from test_package_technical_execution_pg import formal_refusal

    saved, identity = prepare(exact)
    path = exact["technical_base"] + "/technical-scopes/" + saved["manifest"]["id"]
    formal_refusal(exact, saved, path, "installed")
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM score_execution.jobs WHERE input_id=%s", (identity,)
            ).fetchone()["n"]
            == 0
        )
