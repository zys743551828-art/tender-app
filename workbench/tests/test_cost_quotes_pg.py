"""Native prices and complete-input quotes; synthetic configuration, zero spend."""
# ruff: noqa: F401,F811

import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_input_seals_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    requirements,
    saved,
    seal,
    world,
)
from test_input_seals_pg import (
    database as seal_database,
)
from test_input_seals_pg import (
    ready as seal_ready,
)
from test_package_current_original_set_pg import wire
from test_package_material_cost import policy_data

from packages.domain.review_identity import digest
from packages.model_governance import material_cost_quotes as quotes
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_COST_QUOTES_PG") != "1", reason="explicit native quote fixture required"
)
QUOTER = "fusion_material_cost_quoter"
OTHER = "fusion_other_material_cost_quoter"


@pytest.fixture(scope="module")
def database():
    base = seal_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    installed = False
    created = []
    try:
        owner.execute(quotes.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role in (QUOTER, OTHER):
            assert not owner.execute("SELECT FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            created.append(role)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(quotes.GROUP), sql.Identifier(role))
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[QUOTER]() as c, factories[OTHER]() as other:
            yield value | {
                "cost_quoter": c,
                "cost_quoter_factory": factories[QUOTER],
                "other_cost_quoter": other,
            }
    finally:
        try:
            next(base)
        except StopIteration:
            pass
        finally:
            if installed:
                with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
                    for role in created:
                        admin.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )
                    admin.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(quotes.GROUP))
                    )


def publish(w, sealed, *, price_changes=None, valid_for_seconds=3600, **changes):
    owner = w["database"]["owner"]
    now = datetime.now(timezone.utc)
    identifier = str(uuid4())
    price = (
        policy_data()
        | {
            "policy_id": identifier,
            "source_observed_at": (now - timedelta(seconds=30)).isoformat(),
            "valid_from": (now - timedelta(seconds=30)).isoformat(),
            "valid_until": (now + timedelta(seconds=valid_for_seconds)).isoformat(),
        }
        | (price_changes or {})
    )
    values = {
        "id": identifier,
        "quote_login": QUOTER,
        "quote_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (QUOTER,)
        ).fetchone()["oid"],
        "seal_profile_id": sealed.metadata["document"]["profile_id"],
        "origin": "synthetic_mechanism",
        "quote_method_digest": quotes.method_digest(),
        "quote_sql_method_digest": owner.execute(
            "SELECT material_cost_quote.native_method_digest() AS v"
        ).fetchone()["v"],
        "cost_method_digest": cost.method_digest(),
        "provider_profile_digest": vision.profile_digest(),
        "serializer_digest": vision.serializer_digest(),
        "judgment_method_digest": vision.judgment_method_digest(),
        "price_policy": Jsonb(price),
        "price_policy_digest": digest(price),
        "max_attempts_per_slot": 5,
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
    } | changes
    owner.execute(
        sql.SQL("INSERT INTO material_cost_quote.policies ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_cost_quote.policy_heads VALUES(%s,%s,1,true) ON CONFLICT(quote_login) DO UPDATE SET policy_id=excluded.policy_id,revision=excluded.revision,enabled=true",
        (values["quote_login"], identifier),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM material_cost_quote.policies p WHERE id=%s",
        (identifier,),
    ).fetchone()["v"]
    return {
        "seal_id": sealed.metadata["document"]["seal_id"],
        "expected_seal_digest": sealed.metadata["digest"],
        "policy_id": identifier,
        "expected_policy_digest": checksum,
        "command_id": str(uuid4()),
        "max_attempts_per_slot": 5,
        "budget_currency": "USD",
        "budget_ceiling_minor": 10000000000,
        "expected_method_digest": quotes.method_digest(),
    }, price


def ready(wire, monkeypatch, **changes):
    _, ctx, args = seal_ready(wire, monkeypatch)
    sealed = seal(wire[0], args)
    quote_args, price = publish(wire[0], sealed, **changes)
    return sealed, ctx, quote_args, price


def quote(w, args, connection=None):
    return quotes.quote(w["database"]["cost_quoter"] if connection is None else connection, **args)


def reread(w, record):
    with w["database"]["cost_quoter_factory"]() as c:
        return quotes.read(
            c,
            quote_id=record.metadata["document"]["quote_id"],
            expected_quote_digest=record.metadata["digest"],
            expected_method_digest=quotes.method_digest(),
        )


def test_native_full_rules_quote_matches_pure_arithmetic_and_reopens_without_io(wire, monkeypatch):
    w, state, _ = wire
    sealed, ctx, args, price = ready(wire, monkeypatch)
    result = quote(w, args)
    d = result.metadata["document"]
    policy = cost.bind_policy(price, expected_policy_digest=digest(price))
    expected = cost.quote(
        ctx,
        policy,
        expected_context_digest=ctx.metadata["digest"],
        expected_policy_digest=policy.metadata["digest"],
        expected_method_digest=cost.method_digest(),
        as_of=d["recorded_at"],
        max_attempts_per_slot=5,
        budget_currency="USD",
        budget_ceiling_minor=10000000000,
    )
    assert d["quote"] == expected.metadata and d["recorded_by"] == QUOTER
    assert d["seal_digest"] == sealed.metadata["digest"] and d["price_policy_native_verified"]
    assert not any(d[k] for k in quotes.FALSE_FIELDS)
    assert quote(w, args) == result
    observed = reread(w, result)
    assert observed.record == result and observed.metadata["current"]["software_budget_sufficient"]
    assert state["attempts"] == 8
    directory = os.environ.get("FUSION_COST_QUOTES_EVIDENCE")
    if directory:
        (Path(directory) / "cost-quotes-proof.json").write_text(
            json.dumps(
                {
                    "method_digest": quotes.method_digest(),
                    "record": result.metadata,
                    "reopened": observed.metadata,
                    "independent_quoter_login_and_oid": True,
                    "complete_included_rules_from_native_context": True,
                    "exact_pure_quote_metadata_matches": True,
                    "quote_additional_gets": 0,
                    "synthetic_renderer_stub": True,
                    "actual_renderer_used": False,
                    "synthetic_material_and_configuration": True,
                    "account_price_confirmed": False,
                    "fee_ledger_reserved": False,
                    "execution_authorized": False,
                    "input_authority_granted": False,
                    "actual_human_review": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_insufficient_budget_keeps_all_rules_and_retry_slots(wire, monkeypatch):
    w, _, _ = wire
    _, ctx, args, _ = ready(wire, monkeypatch)
    result = quote(w, args | {"budget_ceiling_minor": 0})
    q = result.metadata["document"]["quote"]
    assert result.metadata["document"]["status"] == "quoted_insufficient"
    assert q["rule_ids"] == [
        r["rule_id"] for r in ctx.metadata["rules"] if r["selection"] == "include"
    ]
    assert (
        q["maximum_external_calls"] == len(q["rule_ids"]) * 15
        and q["required_reservation_minor"] > 0
    )
    assert not reread(w, result).metadata["current"]["software_budget_sufficient"]


@pytest.mark.parametrize(
    "key", ["owner", "verification_program", "input_verifier", "input_sealer", "other_cost_quoter"]
)
def test_only_assigned_quoting_identity_can_consume_seal(wire, monkeypatch, key):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch)
    with pytest.raises(quotes.CostQuoteError):
        quote(w, args, w["database"][key])


@pytest.mark.parametrize(
    "field,value",
    [
        ("quote_sql_method_digest", "e" * 64),
        ("provider_profile_digest", "e" * 64),
        ("judgment_method_digest", "e" * 64),
        ("origin", "current_prebid"),
        ("quote_login_oid", 1),
        ("database_oid", 1),
        ("database_name", "wrong_database"),
    ],
)
def test_unapproved_native_method_profile_or_epoch_rejects_quote(wire, monkeypatch, field, value):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch, **{field: value})
    with pytest.raises(quotes.CostQuoteError, match="CURRENT_STATE_UNAVAILABLE"):
        quote(w, args)


@pytest.mark.parametrize(
    "field", ["quote_method_digest", "cost_method_digest", "serializer_digest"]
)
def test_client_rejects_incompatible_method_before_commit(wire, monkeypatch, field):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch, **{field: "d" * 64})
    with pytest.raises(quotes.CostQuoteError, match="NATIVE_RESULT_INVALID"):
        quote(w, args)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_cost_quote.quotes WHERE command_id=%s",
            (args["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_per_million_minor", True),
        ("input_per_million_minor", -1),
        ("output_per_million_minor", "1.2"),
        ("context_token_capacity", 0),
        ("valid_from", "2026-10-24T00:00:00"),
        ("valid_until", "2020-01-01T00:00:00Z"),
        ("valid_until", "2030-01-01T00:00:00Z"),
    ],
)
def test_invalid_price_types_time_window_or_expiration_never_quote(wire, monkeypatch, field, value):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch, price_changes={field: value})
    with pytest.raises(quotes.CostQuoteError, match="CURRENT_STATE_UNAVAILABLE"):
        quote(w, args)


def test_full_reservation_overflow_and_wrong_currency_rejected(wire, monkeypatch):
    w, _, _ = wire
    _, _, args, _ = ready(
        wire, monkeypatch, price_changes={"input_per_million_minor": cost.SAFE_INTEGER}
    )
    with pytest.raises(quotes.CostQuoteError, match="AMOUNT_OVERFLOW"):
        quote(w, args)
    with pytest.raises(quotes.CostQuoteError, match="BUDGET_INVALID"):
        quote(w, args | {"budget_currency": "CNY"})


def test_policy_attempt_limit_and_explicit_cny_without_conversion(wire, monkeypatch):
    w, _, _ = wire
    _, _, args, _ = ready(
        wire, monkeypatch, price_changes={"currency": "CNY"}, max_attempts_per_slot=1
    )
    with pytest.raises(quotes.CostQuoteError, match="BUDGET_INVALID"):
        quote(w, args | {"budget_currency": "CNY"})
    result = quote(w, args | {"budget_currency": "CNY", "max_attempts_per_slot": 1})
    q = result.metadata["document"]["quote"]
    assert q["currency"] == "CNY" and q["minor_per_unit"] == 1000000
    assert q["maximum_external_calls"] == len(q["rule_ids"]) * 3


def test_price_expiration_preserves_fact_and_blocks_new_reservation_readiness(wire, monkeypatch):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch, valid_for_seconds=2)
    result = quote(w, args)
    policy_end = datetime.fromisoformat(result.metadata["document"]["price_policy"]["valid_until"])
    remaining = (policy_end - datetime.now(timezone.utc)).total_seconds()
    assert remaining <= 2
    time.sleep(max(0, remaining) + 0.05)
    observed = reread(w, result)
    assert observed.record == result and not observed.metadata["current"]["price_effective"]
    assert (
        not observed.metadata["current"]["software_budget_sufficient"] and quote(w, args) == result
    )
    with pytest.raises(quotes.CostQuoteError, match="CURRENT_STATE_UNAVAILABLE"):
        quote(w, args | {"command_id": str(uuid4())})


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE material_cost_quote.policy_heads SET enabled=false,revision=revision+1",
        "UPDATE material_cost_quote.policy_heads SET revision=revision+1",
        "UPDATE material_input_seal.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE material_input_authority.policy_heads SET revision=revision+1",
        "UPDATE design.bid_profiles SET phase='closed'",
    ],
)
def test_current_quote_validity_separate_from_old_immutable_amounts(wire, monkeypatch, mutation):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch)
    result = quote(w, args)
    w["database"]["owner"].execute(mutation)
    observed = reread(w, result)
    assert observed.record == result and not observed.metadata["current"]["software_quote_current"]
    assert quote(w, args) == result
    if (
        "enabled=false" in mutation
        or "phase=" in mutation
        or "material_input_authority" in mutation
    ):
        with pytest.raises(quotes.CostQuoteError, match="CURRENT_STATE_UNAVAILABLE"):
            quote(w, args | {"command_id": str(uuid4())})


def test_four_connections_same_logical_quote_and_changed_budget_conflict(wire, monkeypatch):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch)

    def run(_):
        with w["database"]["cost_quoter_factory"]() as c:
            return quote(w, args, c)

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(row == rows[0] for row in rows)
    with pytest.raises(quotes.CostQuoteError, match="COMMAND_CONFLICT"):
        quote(w, args | {"budget_ceiling_minor": 0})
    with pytest.raises(quotes.CostQuoteError, match="COMMAND_CONFLICT"):
        quote(w, args | {"max_attempts_per_slot": 1})


@pytest.mark.parametrize(
    "change,restore",
    [
        (
            "GRANT SELECT ON material_cost_quote.quotes TO PUBLIC",
            "REVOKE SELECT ON material_cost_quote.quotes FROM PUBLIC",
        ),
        (
            "GRANT EXECUTE ON FUNCTION material_cost_quote.current_context(uuid,uuid) TO tender_material_cost_quote",
            "REVOKE EXECUTE ON FUNCTION material_cost_quote.current_context(uuid,uuid) FROM tender_material_cost_quote",
        ),
        (
            "ALTER FUNCTION material_input_seal.current_context(uuid,uuid) SET TimeZone='Asia/Shanghai'",
            "ALTER FUNCTION material_input_seal.current_context(uuid,uuid) SET TimeZone='UTC'",
        ),
    ],
)
def test_overgrants_and_private_dependency_drift_are_rejected(wire, monkeypatch, change, restore):
    w, _, _ = wire
    _, _, args, _ = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    owner.execute(change)
    try:
        with pytest.raises(quotes.CostQuoteError):
            quote(w, args)
    finally:
        owner.execute(restore)
