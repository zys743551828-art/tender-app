"""Dedicated ops-only price/limit/reconciliation CLI; never a business HTTP capability."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


@contextmanager
def admin_connection(profile: Path):
    if profile.is_symlink() or profile.stat().st_mode & 0o077:
        raise ValueError("Dedicated private admin profile required")
    values = {}
    for line in profile.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            fields = shlex.split(value, comments=True)
            if len(fields) != 1:
                raise ValueError("Malformed dedicated admin profile")
            values[key] = fields[0]
    if set(values) != {"ASSISTANT_BUDGET_ADMIN_DATABASE_DSN"}:
        raise ValueError("Budget admin process accepts one dedicated DSN only")
    with psycopg.connect(values["ASSISTANT_BUDGET_ADMIN_DATABASE_DSN"], row_factory=dict_row) as c:
        c.execute("SET LOCAL search_path=design,pg_catalog")
        role = c.execute(
            "SELECT rolsuper,pg_has_role(current_user,'tender_assistant_budget_admin','MEMBER') AS permitted,EXISTS(SELECT FROM pg_class WHERE relnamespace='design'::regnamespace AND relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)) AS owns FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if not role or role["rolsuper"] or role["owns"] or not role["permitted"]:
            raise ValueError("Dedicated nonowner budget admin LOGIN required")
        yield c


def insert_configuration(c, kind, value):
    from psycopg import sql

    fields = {
        "price": (
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
        ),
        "limit": (
            "id",
            "scope",
            "owner_key",
            "currency",
            "revision",
            "limit_minor",
            "window_from",
            "window_until",
            "configured_reason",
        ),
    }
    if kind not in fields or set(value) != set(fields[kind]):
        raise ValueError("Closed explicit price/limit configuration required")
    if kind == "price":
        location = urlsplit(value["source_uri"])
        if location.scheme != "https" or location.username or location.password:
            raise ValueError("Public official source locator required")
        if value[
            "source_kind"
        ] == "official_tariff_and_context_limit" and location.hostname not in {
            "api-docs.deepseek.com",
            "platform.deepseek.com",
        }:
            raise ValueError("Only official provider price/context documentation accepted")
    for key in (
        "amount_scale",
        "input_per_million_minor",
        "output_per_million_minor",
        "input_hard_ceiling",
        "output_hard_ceiling",
        "revision",
        "limit_minor",
    ):
        if key in value and type(value[key]) is not int:
            raise ValueError("Configuration monetary/token quantities require exact integers")
    table = "assistant_price_versions" if kind == "price" else "assistant_budget_versions"
    c.execute(
        sql.SQL("INSERT INTO design.{} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, fields[kind])),
            sql.SQL(",").join(sql.Placeholder() for _ in fields[kind]),
        ),
        tuple(value[key] for key in fields[kind]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("price", "limit", "reconcile"))
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-document", type=Path)
    args = parser.parse_args()
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
        raise ValueError("Run budget admin in its own positive-allowlist process")
    value = json.loads(args.input.read_text())
    if args.kind == "price":
        if (
            not args.source_document
            or hashlib.sha256(args.source_document.read_bytes()).hexdigest()
            != value["source_sha256"]
        ):
            raise ValueError("Retained exact official/synthetic source document is required")
    with admin_connection(args.profile) as c:
        if args.kind == "reconcile":
            if (
                set(value)
                != {"job_id", "decision", "amount_minor", "proof_reference", "proof_sha256"}
                or type(value["amount_minor"]) is not int
            ):
                raise ValueError("Closed trusted reconciliation input required")
            c.execute(
                "SELECT design.assistant_reconcile_budget(%s,%s,%s,%s,%s)",
                (
                    UUID(value["job_id"]),
                    value["decision"],
                    value["amount_minor"],
                    value["proof_reference"],
                    value["proof_sha256"],
                ),
            )
        else:
            insert_configuration(c, args.kind, value)
    print(
        {
            "configured": args.kind,
            "real_provider_attempts": 0,
            "not_external_fee_authorization": True,
        }
    )


if __name__ == "__main__":
    main()
