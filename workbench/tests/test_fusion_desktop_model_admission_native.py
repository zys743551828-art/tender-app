"""Opt-in real PG17 admission through an isolated nonowner budget administrator."""

from __future__ import annotations

import base64
import copy
import json
import os
import shlex
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from deploy import fusion_desktop_model_admission as admission


@pytest.fixture
def native_admission(tmp_path):
    location = os.environ.get("MODEL_ADMISSION_NATIVE_INPUT")
    if not location:
        pytest.skip("Explicit disposable PG17 budget administrator harness required")
    config = json.loads(Path(location).read_text())
    parameters = conninfo_to_dict(config["dsn"])
    assert parameters["host"] == "model-admission-pg"
    assert parameters["dbname"] == "model_admission_disposable"
    assert parameters["user"] == "model_admission_admin"
    profile = tmp_path / "budget.env"
    profile.write_text("ASSISTANT_BUDGET_ADMIN_DATABASE_DSN=" + shlex.quote(config["dsn"]) + "\n")
    profile.chmod(0o600)
    public = Path("/public/admission.json")
    packet = json.loads(public.read_text())
    source = public.parent / packet.pop("source_document")
    packet["source_base64"] = base64.b64encode(source.read_bytes()).decode("ascii")
    packet["price"]["id"] = str(uuid4())
    packet["price"]["version"] += "-" + uuid4().hex
    packet["limit"]["id"] = str(uuid4())
    packet["limit"]["revision"] = int(uuid4().hex[:10], 16)
    return profile, packet, config["identity"]


@pytest.mark.parametrize(
    ("scale", "constraint"),
    [
        (1_000_000, "assistant_price_versions_amount_scale_check"),
        (1_000_000_000, "assistant_price_versions_output_hard_ceiling_check"),
    ],
)
def test_original_public_input_has_real_pg_check_violation(native_admission, scale, constraint):
    profile, packet, identity = native_admission
    packet["price"]["amount_scale"] = scale
    # This intentionally bypasses the admission validator to prove the retained
    # original packet's database incompatibility using the actual restricted role.
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        with admission.budget_admin.admin_connection(profile) as connection:
            admission.budget_admin.insert_configuration(connection, "price", packet["price"])
    assert caught.value.sqlstate == "23514"
    assert caught.value.diag.constraint_name == constraint


def test_real_nonowner_atomic_idempotent_admission(native_admission):
    profile, original, identity = native_admission
    packet = copy.deepcopy(original)
    # The schema uses billionths of the selected currency and caps the software
    # request output at 8192; these are not changes to the provider's context.
    packet["price"].update(
        amount_scale=1_000_000_000,
        input_per_million_minor=2_000_000_000,
        output_per_million_minor=8_000_000_000,
        output_hard_ceiling=8192,
    )
    packet["limit"]["limit_minor"] = 1_000_000_000_000
    for _ in range(2):
        admission.apply(profile, packet, "deepseek-flash", identity)
    with admission.budget_admin.admin_connection(profile) as connection:
        assert connection.info.server_version // 10000 == 17
        role = connection.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert not any(role.values())
        amount = connection.execute(
            "SELECT ceil((1000000::numeric*%s+8192::numeric*%s)/1000000)::bigint AS amount",
            (
                packet["price"]["input_per_million_minor"],
                packet["price"]["output_per_million_minor"],
            ),
        ).fetchone()["amount"]
        assert amount == 2_065_536_000  # 2.065536 CNY at the unchanged 1e9 scale.
        for kind, table in (
            ("price", "assistant_price_versions"),
            ("limit", "assistant_budget_versions"),
        ):
            row = connection.execute(
                admission.sql.SQL("SELECT * FROM design.{} WHERE id=%s").format(
                    admission.sql.Identifier(table)
                ),
                (packet[kind]["id"],),
            ).fetchone()
            assert admission.equivalent(row, packet[kind])
    invalid = copy.deepcopy(packet)
    invalid["price"]["id"] = str(uuid4())
    invalid["price"]["version"] += "-rollback"
    invalid["limit"]["id"] = str(uuid4())
    # Existing unique (scope, owner_key, revision) fails after the new price.
    with pytest.raises(psycopg.errors.UniqueViolation):
        admission.apply(profile, invalid, "deepseek-flash", identity)
    with admission.budget_admin.admin_connection(profile) as connection:
        assert (
            connection.execute(
                "SELECT id FROM design.assistant_price_versions WHERE id=%s",
                (invalid["price"]["id"],),
            ).fetchone()
            is None
        )
