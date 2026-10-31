"""Offline admission boundaries and atomic purpose-role writes; no provider/DB calls."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from deploy import fusion_desktop_model_admission as admission


@pytest.fixture
def packet():
    now = datetime.now(timezone.utc)
    source = b"SYNTHETIC retained source for offline contract tests only."
    return {
        "version": admission.VERSION,
        "source_base64": base64.b64encode(source).decode(),
        "price": {
            "id": str(uuid4()),
            "version": "synthetic-unit-tariff",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "currency": "CNY",
            "amount_scale": 1000000000,
            "input_per_million_minor": 1,
            "output_per_million_minor": 2,
            "input_hard_ceiling": 1000,
            "output_hard_ceiling": 100,
            "source_kind": "official_tariff_and_context_limit",
            "source_uri": "https://api-docs.deepseek.com/quick_start/pricing",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "verified_at": (now - timedelta(minutes=1)).isoformat(),
            "valid_from": (now - timedelta(days=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
        "limit": {
            "id": str(uuid4()),
            "scope": "global",
            "owner_key": "assistant",
            "currency": "CNY",
            "revision": 1,
            "limit_minor": 100,
            "window_from": (now - timedelta(days=1)).isoformat(),
            "window_until": (now + timedelta(days=1)).isoformat(),
            "configured_reason": "Explicit synthetic offline test only",
        },
    }


def write_input(tmp_path, packet, source_document="source.html"):
    source = base64.b64decode(packet["source_base64"])
    (tmp_path / "source.html").write_bytes(source)
    data = {k: copy.deepcopy(v) for k, v in packet.items() if k != "source_base64"}
    data["source_document"] = source_document
    path = tmp_path / "admission.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_public_file_retains_source_sha_without_credentials_or_new_defaults(tmp_path, packet):
    assert admission.load_file(write_input(tmp_path, packet)) == packet


@pytest.mark.parametrize(
    "path", ["../source.html", "/outside.html", "C:\\private\\source.html", "source.env"]
)
def test_public_source_cannot_escape_or_select_private_env(tmp_path, packet, path):
    with pytest.raises(admission.spec.ConfigurationError):
        admission.load_file(write_input(tmp_path, packet, path))


def test_symlink_source_is_rejected_before_read(tmp_path, packet, monkeypatch):
    path = write_input(tmp_path, packet)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == tmp_path / "source.html" or original(p))
    with pytest.raises(admission.spec.ConfigurationError):
        admission.load_file(path)


@pytest.mark.parametrize(
    "fault", ["synthetic", "expired", "hash", "boolean", "currency", "infinite", "secret", "model"]
)
def test_invalid_or_unqualified_admission_rejected(packet, fault):
    if fault == "synthetic":
        packet["price"]["source_kind"] = "synthetic"
    elif fault == "expired":
        packet["price"]["valid_until"] = "2000-01-01T00:00:00+00:00"
    elif fault == "hash":
        packet["price"]["source_sha256"] = "0" * 64
    elif fault == "boolean":
        packet["limit"]["limit_minor"] = True
    elif fault == "currency":
        packet["limit"]["currency"] = "USD"
    elif fault == "infinite":
        packet["limit"]["limit_minor"] = 2**64
    elif fault == "secret":
        packet["DEEPSEEK_API_KEY"] = "synthetic-private-marker"
    else:
        packet["price"]["model"] = "deepseek-v4-pro"
    with pytest.raises(admission.spec.ConfigurationError):
        admission.validate(packet, model="deepseek-flash")


def test_source_and_packet_budgets_are_bounded(tmp_path, packet):
    path = write_input(tmp_path, packet)
    (tmp_path / "source.html").write_bytes(b"x" * (admission.MAX_SOURCE + 1))
    with pytest.raises(admission.spec.ConfigurationError):
        admission.load_file(path)
    packet["source_base64"] = "x" * (admission.MAX_PACKET + 1)
    with pytest.raises(admission.spec.ConfigurationError):
        admission.validate(packet)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("amount_scale", 1_000_000, "AMOUNT_SCALE_INVALID"),
        ("output_hard_ceiling", 384_000, "SCHEMA_LIMIT_INVALID"),
        ("input_hard_ceiling", 2_097_153, "SCHEMA_LIMIT_INVALID"),
        ("input_per_million_minor", 0, "SCHEMA_LIMIT_INVALID"),
        ("output_per_million_minor", 1_000_000_000_001, "SCHEMA_LIMIT_INVALID"),
    ],
)
def test_schema_quantities_rejected_before_database(packet, database, tmp_path, field, value, code):
    packet["price"][field] = value
    with pytest.raises(admission.spec.ConfigurationError, match=code):
        admission.apply(tmp_path / "unused.env", packet, "deepseek-flash", database.identity)
    assert database.opened == []


def test_database_error_reports_only_public_type_and_sqlstate(monkeypatch, capsys):
    from psycopg.errors import InsufficientPrivilege

    def denied(*_):
        raise InsufficientPrivilege("private profile and database detail must not escape")

    monkeypatch.setattr(admission, "check_and_apply", denied)
    assert admission.main(["--check"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "ok": False,
        "code": "DESKTOP_MODEL_ADMISSION_DATABASE_FAILED",
        "error_type": "InsufficientPrivilege",
        "sqlstate": "42501",
    }


@pytest.mark.parametrize(
    "relative",
    [
        "/outside/admin.env",
        ".local/../../owner.env",
        ".local/not-admin.env",
        ".local/..\\owner-assistant_budget_admin.env",
        ".local/C:owner-assistant_budget_admin.env",
    ],
)
def test_receipt_cannot_select_owner_or_arbitrary_profile(tmp_path, relative):
    with pytest.raises(admission.spec.ConfigurationError):
        admission.budget_profile(
            tmp_path, {"bootstrap_profiles": {"assistant_budget_admin": relative}}
        )


@pytest.fixture
def database(monkeypatch):
    class Database:
        def __init__(self):
            self.rows = {"price": {}, "limit": {}}
            self.identity = {"database": "owned-synthetic", "login": "dedicated-budget-login"}
            self.opened = []
            self.inserts = []
            self.fail_limit = False

        def execute(self, query, params=()):
            text = str(query)
            if "current_database()" in text:
                return SimpleNamespace(fetchone=lambda: self.identity)
            kind = "price" if "assistant_price_versions" in text else "limit"
            if "INSERT" in text:
                self.inserts.append(kind)
                if kind == "limit" and self.fail_limit:
                    raise ValueError("synthetic-private-db-error")
                fields = admission.PRICE_FIELDS if kind == "price" else admission.LIMIT_FIELDS
                value = dict(zip(fields, params, strict=True))
                value = {
                    k: admission.timestamp(v)
                    if k in admission.DATES
                    else UUID(v)
                    if k == "id"
                    else v
                    for k, v in value.items()
                }
                self.rows[kind][str(value["id"])] = value
                return None
            return SimpleNamespace(fetchone=lambda: self.rows[kind].get(str(params[0])))

    database = Database()

    @contextmanager
    def purpose_connection(profile):
        database.opened.append(profile)
        before = copy.deepcopy(database.rows)
        try:
            yield database
        except Exception:
            database.rows = before
            raise

    monkeypatch.setattr(admission.budget_admin, "admin_connection", purpose_connection)
    return database


def test_existing_identical_ids_are_idempotent_using_original_budget_insert(
    packet, database, tmp_path
):
    profile = tmp_path / "dedicated-purpose.env"
    for _ in range(2):
        admission.apply(profile, packet, "deepseek-flash", database.identity)
    assert database.inserts == ["price", "limit"]
    assert database.opened == [profile, profile]


def test_changed_existing_id_conflicts_without_overwriting(packet, database, tmp_path):
    profile = tmp_path / "dedicated-purpose.env"
    admission.apply(profile, packet, "deepseek-flash", database.identity)
    before = copy.deepcopy(database.rows)
    packet["price"]["version"] = "changed"
    with pytest.raises(admission.spec.ConfigurationError, match="ADMISSION_CONFLICT"):
        admission.apply(profile, packet, "deepseek-flash", database.identity)
    assert database.rows == before


def test_limit_failure_rolls_back_new_price(packet, database, tmp_path):
    database.fail_limit = True
    with pytest.raises(ValueError):
        admission.apply(tmp_path / "dedicated.env", packet, "deepseek-flash", database.identity)
    assert database.rows == {"price": {}, "limit": {}}
    assert database.inserts == ["price", "limit"]


def test_other_database_is_rejected_before_any_insert(packet, database, tmp_path):
    with pytest.raises(admission.spec.ConfigurationError, match="DATABASE_BINDING"):
        admission.apply(
            tmp_path / "dedicated.env",
            packet,
            "deepseek-flash",
            {"database": "other", "login": "other"},
        )
    assert not database.inserts


def test_existing_admission_check_only_keeps_configuration_read_only(monkeypatch, tmp_path):
    for key in (
        "API_DATABASE_DSN",
        "WORKER_DATABASE_DSN",
        "OWNER_DATABASE_DSN",
        "DEEPSEEK_API_KEY",
        "OBJECT_STORE_ACCESS_KEY",
        "OBJECT_STORE_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    observed = []

    def load(path):
        role = path.parent.name
        return {
            "role": role,
            "plan": {"model_configured": True},
            "environment": {"DEEPSEEK_MODEL": "deepseek-flash"},
        }

    monkeypatch.setattr(admission.spec, "load_private_json", load)
    monkeypatch.setattr(admission.spec, "validate_role", lambda p: None)
    monkeypatch.setattr(admission.probe, "check", lambda p: observed.append(p["role"]))
    monkeypatch.setattr(admission, "apply", lambda *_: pytest.fail("check-only must not write"))
    result = admission.check_and_apply(directory=tmp_path)
    assert observed == ["paid_worker", "paid_controller"]
    assert result["configuration_supplied"] is False and result["provider_calls"] == 0


@pytest.mark.parametrize("code", ["FULL_OFFICIAL_PRICE_REQUIRED", "FULL_GLOBAL_BUDGET_REQUIRED"])
def test_missing_admission_has_actionable_nonzero_code(monkeypatch, capsys, code):
    def missing(*_):
        raise admission.spec.ConfigurationError(code)

    monkeypatch.setattr(admission, "check_and_apply", missing)
    assert admission.main(["--check"]) == 3
    assert json.loads(capsys.readouterr().out)["code"] == "DESKTOP_MODEL_ADMISSION_REQUIRED"
