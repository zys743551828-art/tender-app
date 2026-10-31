"""Explicit public model admission data; dedicated nonowner budget configuration only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import UUID

from psycopg import IntegrityError, sql

from deploy import fusion_full_probe as probe
from deploy import fusion_full_spec as spec
from deploy.fusion_desktop_compose import PRIVATE
from packages.assistant import budget_admin

VERSION = "fusion-desktop-model-admission/1"
MAX_FILE = 32768
MAX_SOURCE = 131072
MAX_PACKET = 200000
PRICE_FIELDS = (
    "id",
    "version",
    "provider",
    "model",
    "currency",
    "amount_scale",
    "input_per_million_minor",
    "output_per_million_minor",
    "input_hard_ceiling",
    "output_hard_ceiling",
    "source_kind",
    "source_uri",
    "source_sha256",
    "verified_at",
    "valid_from",
    "valid_until",
)
LIMIT_FIELDS = (
    "id",
    "scope",
    "owner_key",
    "currency",
    "revision",
    "limit_minor",
    "window_from",
    "window_until",
    "configured_reason",
)
DATES = {"verified_at", "valid_from", "valid_until", "window_from", "window_until"}


def fail(code):
    raise spec.ConfigurationError(code)


def public_file(path, maximum):
    path = Path(path)
    before = path.lstat()
    if (
        path.is_symlink()
        or getattr(before, "st_file_attributes", 0) & 0x400
        or not stat.S_ISREG(before.st_mode)
        or not 0 < before.st_size <= maximum
    ):
        fail("DESKTOP_MODEL_ADMISSION_FILE_INVALID")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        raw = handle.read(maximum + 1)
        after = os.fstat(handle.fileno())
    if (
        (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        or len(raw) != opened.st_size
        or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    ):
        fail("DESKTOP_MODEL_ADMISSION_FILE_CHANGED")
    return raw


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        fail("DESKTOP_MODEL_ADMISSION_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        fail("DESKTOP_MODEL_ADMISSION_TIME_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail("DESKTOP_MODEL_ADMISSION_TIME_INVALID")
    return parsed


def validate(packet, *, model=None, now=None):
    if (
        not isinstance(packet, dict)
        or set(packet) != {"version", "price", "limit", "source_base64"}
        or packet["version"] != VERSION
    ):
        fail("DESKTOP_MODEL_ADMISSION_INPUT_INVALID")
    price, limit = packet["price"], packet["limit"]
    if (
        not isinstance(price, dict)
        or set(price) != set(PRICE_FIELDS)
        or not isinstance(limit, dict)
        or set(limit) != set(LIMIT_FIELDS)
    ):
        fail("DESKTOP_MODEL_ADMISSION_INPUT_INVALID")
    integer_fields = {
        "amount_scale",
        "input_per_million_minor",
        "output_per_million_minor",
        "input_hard_ceiling",
        "output_hard_ceiling",
        "revision",
        "limit_minor",
    }
    for value in (price, limit):
        for key, item in value.items():
            if key not in integer_fields and (
                not isinstance(item, str)
                or not 0 < len(item) <= 2048
                or any(c in item for c in "\r\n\x00")
            ):
                fail("DESKTOP_MODEL_ADMISSION_INPUT_INVALID")
    if not isinstance(packet["source_base64"], str) or len(packet["source_base64"]) > MAX_PACKET:
        fail("DESKTOP_MODEL_ADMISSION_INPUT_TOO_LARGE")
    try:
        UUID(price["id"])
        UUID(limit["id"])
        raw = base64.b64decode(packet["source_base64"], validate=True)
    except (ValueError, TypeError):
        fail("DESKTOP_MODEL_ADMISSION_INPUT_INVALID")
    if not 0 < len(raw) <= MAX_SOURCE or hashlib.sha256(raw).hexdigest() != price["source_sha256"]:
        fail("DESKTOP_MODEL_ADMISSION_SOURCE_MISMATCH")
    uri = urlsplit(price["source_uri"])
    if (
        price["source_kind"] != "official_tariff_and_context_limit"
        or uri.scheme != "https"
        or uri.hostname not in {"api-docs.deepseek.com", "platform.deepseek.com"}
        or uri.username
        or uri.password
    ):
        fail("DESKTOP_MODEL_ADMISSION_OFFICIAL_SOURCE_REQUIRED")
    if (
        price["provider"] != "deepseek"
        or price["model"] not in {"deepseek-flash", "deepseek-v4-pro"}
        or (model is not None and price["model"] != model)
    ):
        fail("DESKTOP_MODEL_ADMISSION_MODEL_MISMATCH")
    if (
        not isinstance(price["currency"], str)
        or not re.fullmatch("[A-Z]{3}", price["currency"])
        or limit["currency"] != price["currency"]
        or limit["scope"] != "global"
        or limit["owner_key"] != "assistant"
    ):
        fail("DESKTOP_MODEL_ADMISSION_LIMIT_INVALID")
    for value, names in [
        (
            price,
            (
                "amount_scale",
                "input_per_million_minor",
                "output_per_million_minor",
                "input_hard_ceiling",
                "output_hard_ceiling",
            ),
        ),
        (limit, ("revision", "limit_minor")),
    ]:
        for key in names:
            if type(value[key]) is not int or not 0 <= value[key] <= 2**63 - 1:
                fail("DESKTOP_MODEL_ADMISSION_INTEGER_REQUIRED")
    if (
        min(
            price["amount_scale"],
            price["input_hard_ceiling"],
            price["output_hard_ceiling"],
            limit["revision"],
            limit["limit_minor"],
        )
        <= 0
    ):
        fail("DESKTOP_MODEL_ADMISSION_LIMIT_INVALID")
    current = now or datetime.now(timezone.utc)
    if (
        not timestamp(price["valid_from"]) <= current < timestamp(price["valid_until"])
        or timestamp(price["verified_at"]) > current
        or not timestamp(limit["window_from"]) <= current < timestamp(limit["window_until"])
    ):
        fail("DESKTOP_MODEL_ADMISSION_NOT_CURRENT")
    return packet


def load_file(path):
    try:
        path = Path(path).absolute()
        if (
            path.parent.is_symlink()
            or getattr(path.parent.lstat(), "st_file_attributes", 0) & 0x400
        ):
            fail("DESKTOP_MODEL_ADMISSION_SOURCE_PATH_INVALID")
        value = json.loads(public_file(path, MAX_FILE))
        if not isinstance(value, dict) or set(value) != {
            "version",
            "price",
            "limit",
            "source_document",
        }:
            fail("DESKTOP_MODEL_ADMISSION_FILE_INVALID")
        relative = PurePosixPath(value.pop("source_document"))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in str(relative)
            or not relative.parts
            or relative.suffix.lower() not in {".html", ".htm", ".md", ".txt", ".json"}
        ):
            fail("DESKTOP_MODEL_ADMISSION_SOURCE_PATH_INVALID")
        source = path.parent.joinpath(*relative.parts)
        if not source.resolve().is_relative_to(path.parent.resolve()) or any(
            parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400
            for parent in [source, *source.parents]
            if parent != path.parent and path.parent in parent.parents
        ):
            fail("DESKTOP_MODEL_ADMISSION_SOURCE_PATH_INVALID")
        value["source_base64"] = base64.b64encode(public_file(source, MAX_SOURCE)).decode("ascii")
        packet = validate(value)
        if len(json.dumps(packet).encode()) > MAX_PACKET:
            fail("DESKTOP_MODEL_ADMISSION_INPUT_TOO_LARGE")
        return packet
    except spec.ConfigurationError:
        raise
    except Exception:
        fail("DESKTOP_MODEL_ADMISSION_FILE_INVALID")


def budget_profile(directory, receipt):
    relative = PurePosixPath(receipt["bootstrap_profiles"]["assistant_budget_admin"])
    if (
        len(relative.parts) != 2
        or relative.parts[0] != ".local"
        or "\\" in str(relative)
        or ":" in str(relative)
        or not re.fullmatch(r"[A-Za-z0-9_-]+-assistant_budget_admin\.env", relative.name)
    ):
        fail("DESKTOP_MODEL_ADMISSION_PROFILE_INVALID")
    path = spec.fresh.ROOT.joinpath(*relative.parts)
    before = path.lstat()
    if (
        path.parent.is_symlink()
        or path.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or before.st_mode & 0o077
        or not 0 < before.st_size <= 16384
    ):
        fail("DESKTOP_MODEL_ADMISSION_PROFILE_INVALID")
    return path


def equivalent(row, value):
    for key, expected in value.items():
        actual = row[key]
        if key in DATES:
            expected = timestamp(expected)
        elif key == "id":
            expected = UUID(expected)
        if actual != expected:
            return False
    return True


def apply(profile, packet, model, expected_identity):
    packet = validate(packet, model=model)
    # admin_connection owns one transaction: a failing limit never commits its price.
    with budget_admin.admin_connection(profile) as connection:
        actual = connection.execute(
            "SELECT current_database() AS database,current_user AS login"
        ).fetchone()
        if actual != expected_identity:
            fail("DESKTOP_MODEL_ADMISSION_DATABASE_BINDING_INVALID")
        for kind, table, fields in [
            ("price", "assistant_price_versions", PRICE_FIELDS),
            ("limit", "assistant_budget_versions", LIMIT_FIELDS),
        ]:
            value = packet[kind]
            row = connection.execute(
                sql.SQL("SELECT {} FROM design.{} WHERE id=%s").format(
                    sql.SQL(",").join(map(sql.Identifier, fields)), sql.Identifier(table)
                ),
                (UUID(value["id"]),),
            ).fetchone()
            if row is not None:
                if not equivalent(row, value):
                    fail("DESKTOP_MODEL_ADMISSION_CONFLICT")
            else:
                budget_admin.insert_configuration(connection, kind, value)


def check_and_apply(packet=None, *, directory=Path(PRIVATE)):
    if any(
        os.environ.get(key)
        for key in (
            "API_DATABASE_DSN",
            "WORKER_DATABASE_DSN",
            "OWNER_DATABASE_DSN",
            "DEEPSEEK_API_KEY",
            "OBJECT_STORE_ACCESS_KEY",
            "OBJECT_STORE_SECRET_KEY",
        )
    ):
        fail("DESKTOP_MODEL_ADMISSION_ENVIRONMENT_INVALID")
    profiles = [
        spec.load_private_json(directory / "runtime" / role / "profile.json")
        for role in ("paid_worker", "paid_controller")
    ]
    for role, profile in zip(("paid_worker", "paid_controller"), profiles, strict=True):
        spec.validate_role(profile)
        if profile["role"] != role or not profile["plan"]["model_configured"]:
            fail("DESKTOP_MODEL_ADMISSION_PROFILE_INVALID")
    models = {profile["environment"]["DEEPSEEK_MODEL"] for profile in profiles}
    if len(models) != 1:
        fail("DESKTOP_MODEL_ADMISSION_MODEL_MISMATCH")
    if packet is not None:
        receipt = spec.load_private_json(directory / "runtime-receipt.json")
        if any(
            profile["plan_digest"] != receipt["plan_digest"]
            or profile["database"] != receipt["database"]
            for profile in profiles
        ):
            fail("DESKTOP_MODEL_ADMISSION_DATABASE_BINDING_INVALID")
        expected = {
            "database": receipt["database"],
            "login": receipt["logins"]["assistant_budget_admin"],
        }
        apply(budget_profile(directory, receipt), packet, models.pop(), expected)
    for profile in profiles:
        probe.check(profile)
    return {
        "ok": True,
        "stage": "model_admission_verified",
        "configuration_supplied": packet is not None,
        "provider_calls": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--apply-stdin", action="store_true")
    args = parser.parse_args(argv)
    try:
        packet = None
        if args.apply_stdin:
            raw = sys.stdin.buffer.read(MAX_PACKET + 1)
            if len(raw) > MAX_PACKET:
                fail("DESKTOP_MODEL_ADMISSION_INPUT_TOO_LARGE")
            packet = validate(json.loads(raw))
        result = check_and_apply(packet)
    except spec.ConfigurationError as error:
        required = str(error) in {"FULL_OFFICIAL_PRICE_REQUIRED", "FULL_GLOBAL_BUDGET_REQUIRED"}
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "DESKTOP_MODEL_ADMISSION_REQUIRED"
                    if required
                    else str(error)
                    if re.fullmatch("[A-Z0-9_]{1,128}", str(error))
                    else "DESKTOP_MODEL_ADMISSION_FAILED",
                }
            )
        )
        return 3 if required else 2
    except IntegrityError:
        print(json.dumps({"ok": False, "code": "DESKTOP_MODEL_ADMISSION_CONFLICT"}))
        return 2
    except Exception:
        print(json.dumps({"ok": False, "code": "DESKTOP_MODEL_ADMISSION_FAILED"}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
