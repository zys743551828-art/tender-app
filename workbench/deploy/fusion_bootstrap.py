"""Initialize only the isolated fusion base. Replays validate; partial state is never repaired."""

import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import psycopg
from psycopg import sql

from deploy import bootstrap_fresh as fresh
from deploy.fusion_runtime import API_KEYS
from deploy.initialize_database import file_configuration

ORIGIN = "http://127.0.0.1:5188"
# Explicit new preview, preserving the prior database and its private volume pair.
PREVIEW_NAME = "fusion_v10"
DATABASE = "tender_checks_" + PREVIEW_NAME


def main():
    os.umask(0o077)
    state = fresh.ROOT / ".local"
    state.mkdir(mode=0o700, exist_ok=True)
    state.chmod(0o700)
    runtime = Path("/runtime")
    runtime.chmod(0o700)
    receipt_path = state / "fusion-receipt.json"
    api_profile = runtime / "api.env"
    owner_password = (
        Path("/run/secrets/fusion_owner_password").read_text(encoding="utf-8").rstrip("\r\n")
    )
    admin_password = (
        Path("/run/secrets/fusion_admin_password").read_text(encoding="utf-8").rstrip("\r\n")
    )
    if not owner_password or not admin_password:
        raise RuntimeError("FUSION_PRIVATE_PASSWORD_REQUIRED")
    owner_dsn = f"postgresql://postgres:{quote(owner_password, safe='')}@postgres:5432/postgres"
    owner = fresh.owner_parameters(owner_dsn)
    if owner["host"] != "postgres" or owner["dbname"] != "postgres":
        raise RuntimeError("FUSION_ISOLATED_OWNER_REQUIRED")
    plan = fresh.sql_plan(())
    fingerprint = [{"path": p.path, "sha256": p.sha256} for p in plan]
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["ordered_sql"] != fingerprint or receipt["database"] != DATABASE:
            raise RuntimeError("FUSION_BASE_PLAN_CHANGED_REVIEW_REQUIRED")
        from deploy.fusion_runtime import api_environment

        values = api_environment(api_profile)
        with psycopg.connect(values["API_DATABASE_DSN"]) as c:
            admin = c.execute(
                "SELECT count(*) FROM design.credentials WHERE login_name='admin'"
            ).fetchone()
            if admin is None or admin[0] != 1:
                raise RuntimeError("FUSION_ADMIN_STATE_INVALID")
        print(json.dumps({"state": "validated_existing_fusion", "paid_consumers": 0}))
        return
    with psycopg.connect(owner_dsn, autocommit=True) as c:
        if (
            c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)).fetchone()
            or api_profile.exists()
        ):
            raise RuntimeError("FUSION_PARTIAL_STATE_REFUSED")
        for group in fresh.GROUPS:
            if c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (group,)).fetchone() is None:
                c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
    base = state / "fusion-base.env"
    if not base.exists():
        fresh.write_private(
            base, {"OWNER_DATABASE_DSN": owner_dsn, "OBJECT_STORE_PREFIX": "fusion-local-disabled"}
        )
    receipt = fresh.bootstrap(base_profile=base, name=PREVIEW_NAME, app_origin=ORIGIN)
    business = file_configuration(fresh.ROOT / receipt["profiles"]["business"])
    from apps.api.auth import password_hash

    with psycopg.connect(business["API_DATABASE_DSN"]) as c:
        c.execute("SET LOCAL search_path=design,public")
        member = uuid4()
        c.execute("INSERT INTO members(id,display_name) VALUES(%s,'本机管理员')", (member,))
        c.execute(
            "INSERT INTO credentials(member_id,login_name,password_hash) VALUES(%s,'admin',%s)",
            (member, password_hash(admin_password)),
        )
    values = {
        "API_DATABASE_DSN": business["API_DATABASE_DSN"],
        "APP_ORIGIN": ORIGIN,
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "CSRF_SECRET": secrets.token_urlsafe(48),
    }
    if set(values) != API_KEYS:
        raise RuntimeError("FUSION_API_PROFILE_KEYS_INVALID")
    fresh.write_private(api_profile, values)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    receipt_path.chmod(0o600)
    print(json.dumps({"state": "created_fusion_base", "paid_consumers": 0, "database": DATABASE}))


if __name__ == "__main__":
    main()
