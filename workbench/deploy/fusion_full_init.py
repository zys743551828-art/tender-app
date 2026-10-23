"""Fresh isolated full-runtime bootstrap. Existing/partial databases are never repaired."""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from confluent_kafka.admin import AdminClient
from psycopg import sql

from deploy import fusion_full_probe as probe
from deploy import fusion_full_spec as spec
from deploy.fusion_full_dependencies import identity
from deploy.initialize_database import file_configuration
from deploy.initialize_topics import initialize as initialize_topics


def operator(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise spec.ConfigurationError("FULL_PRIVATE_DIRECTORY_REQUIRED")
    value = spec.load_private_json(directory / "operator.json")
    if not isinstance(value, dict) or set(value) != {
        "plan",
        "plan_digest",
        "owner_password",
        "admin_password",
        "store_credentials",
        "session_secret",
        "csrf_secret",
        "model",
    }:
        raise spec.ConfigurationError("FULL_OPERATOR_PROFILE_INVALID")
    plan = value["plan"]
    spec.validate_plan(plan, check_frontend=True)
    if (
        value["plan_digest"] != spec.digest(plan)
        or spec.load_private_json(directory / "plan.json") != plan
    ):
        raise spec.ConfigurationError("FULL_OPERATOR_BINDING_INVALID")
    spec.validate_model(value["model"])
    if plan["model_configured"] != (value["model"] is not None):
        raise spec.ConfigurationError("FULL_MODEL_BINDING_INVALID")
    if any(
        not isinstance(value[key], str) or len(value[key]) < 8
        for key in ("owner_password", "admin_password", "session_secret", "csrf_secret")
    ):
        raise spec.ConfigurationError("FULL_OPERATOR_SECRET_REQUIRED")
    credentials = value["store_credentials"]
    if not isinstance(credentials, dict) or set(credentials) != {"init", "api", "worker"}:
        raise spec.ConfigurationError("FULL_STORE_CREDENTIALS_INVALID")
    for actor in credentials.values():
        if (
            not isinstance(actor, dict)
            or set(actor) != {"access_key", "secret_key"}
            or any(not isinstance(item, str) or len(item) < 16 for item in actor.values())
        ):
            raise spec.ConfigurationError("FULL_STORE_CREDENTIALS_INVALID")
    return value


def store_environment(value, role, prefix):
    plan, credential = value["plan"], value["store_credentials"][role]
    return {
        "OBJECT_STORE_BACKEND": "s3",
        "OBJECT_STORE_ENDPOINT": plan["topology"]["s3_endpoint"],
        "OBJECT_STORE_ACCESS_KEY": credential["access_key"],
        "OBJECT_STORE_SECRET_KEY": credential["secret_key"],
        "OBJECT_STORE_BUCKET": plan["bucket"],
        "OBJECT_STORE_PREFIX": prefix,
        "OBJECT_STORE_REGION": "us-east-1",
    }


def initialize_store(value, *, marker, create):
    client = probe.store_client(store_environment(value, "init", "unused-admin-prefix/"))
    bucket = value["plan"]["bucket"]
    # A started object-store container may not yet have its authenticated S3 listener.
    # Wait only for connection availability; wrong credentials never enter a retry loop.
    deadline = time.monotonic() + 35
    while True:
        try:
            client.list_buckets()
            break
        except ClientError:
            raise spec.ConfigurationError("FULL_STORE_INITIALIZER_NOT_AUTHORIZED") from None
        except BotoCoreError:
            if time.monotonic() >= deadline:
                raise spec.ConfigurationError("FULL_STORE_INITIALIZER_UNAVAILABLE") from None
            time.sleep(0.2)
    if create:
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            client.create_bucket(Bucket=bucket)
        else:
            raise spec.ConfigurationError("FULL_EXISTING_BUCKET_REFUSED")
        # Same-origin object transfer uses API cookies/tickets, so no browser CORS is granted.
        client.put_object(
            Bucket=bucket, Key=marker["key"], Body=marker["bytes"], ContentType="application/json"
        )
    response = client.get_object(Bucket=bucket, Key=marker["key"])
    with response["Body"] as stream:
        actual = stream.read(len(marker["bytes"]) + 1)
    if actual != marker["bytes"]:
        raise spec.ConfigurationError("FULL_OBJECT_BINDING_MISMATCH")


def profiles(value, receipt, business, marker):
    result, plan = {}, value["plan"]
    prefix = receipt["object_store_prefix"]
    for role, allowed in spec.ROLE_KEYS.items():
        if role.startswith("paid_") and not plan["model_configured"]:
            continue
        if role == "task_runner" and not plan["task_runner_enabled"]:
            continue
        worker = "WORKER_DATABASE_DSN" in allowed
        actor = "worker" if worker else "api"
        available = {
            **store_environment(value, actor, prefix),
            "API_DATABASE_DSN": business["API_DATABASE_DSN"],
            "WORKER_DATABASE_DSN": business["WORKER_DATABASE_DSN"],
            "KAFKA_BOOTSTRAP_SERVERS": plan["topology"]["kafka_bootstrap"],
            "APP_ORIGIN": plan["origin"],
            "OBJECT_TRANSFER_MODE": "same_origin",
            "WORD_INTAKE_ENABLED": "1",
            "SESSION_SECRET": value["session_secret"],
            "CSRF_SECRET": value["csrf_secret"],
            **(value["model"] or {}),
        }
        allowed = allowed | (
            spec.MODEL_KEYS
            if role in {"api", "task_runner"} and plan["model_configured"]
            else set()
        )
        result[role] = {
            "version": spec.VERSION,
            "role": role,
            "plan": plan,
            "plan_digest": spec.digest(plan),
            "database": receipt["database"],
            "login": receipt["logins"][actor],
            "runtime": identity(),
            "environment": {key: available[key] for key in sorted(allowed)},
            "probe": {
                "key": marker["key"],
                "sha256": spec.digest(marker["bytes"]),
                "byte_size": len(marker["bytes"]),
            },
        }
        spec.validate_role(result[role])
    return result


def initialize(directory, *, runtime_uid=None):
    directory = Path(directory)
    value = operator(directory)
    plan = value["plan"]
    # The lock is local to this private deployment. A second init cannot overwrite profiles.
    descriptor = os.open(
        directory / "initialize.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise spec.ConfigurationError("FULL_INITIALIZATION_BUSY") from None
        return _initialize_locked(directory, value, plan, runtime_uid=runtime_uid)
    finally:
        os.close(descriptor)


def _initialize_locked(directory, value, plan, *, runtime_uid):
    receipt_path = directory / "runtime-receipt.json"
    marker = {
        "key": "runtime-binding/" + plan["deployment_id"] + ".json",
        "bytes": json.dumps(
            {"deployment_id": plan["deployment_id"], "plan_digest": spec.digest(plan)},
            sort_keys=True,
        ).encode(),
    }
    policy = json.loads((spec.fresh.ROOT / spec.POLICY).read_bytes())
    kafka = AdminClient({"bootstrap.servers": plan["topology"]["kafka_bootstrap"]})
    if receipt_path.exists():
        receipt = spec.load_private_json(receipt_path)
        expected_roles = sorted(
            role
            for role in spec.ROLE_KEYS
            if (not role.startswith("paid_") or plan["model_configured"])
            and (role != "task_runner" or plan["task_runner_enabled"])
        )
        if (
            receipt.get("plan_digest") != spec.digest(plan)
            or receipt.get("database") != "tender_checks_" + plan["name"]
            or receipt.get("runtime_roles") != expected_roles
        ):
            raise spec.ConfigurationError("FULL_EXISTING_PLAN_CHANGED")
        initialize_topics(
            kafka, policy, create_missing=False, expected_cluster_id=plan["kafka_cluster_id"]
        )
        initialize_store(value, marker=marker, create=False)
        for role in receipt["runtime_roles"]:
            profile = spec.load_private_json(directory / "runtime" / role / "profile.json")
            # Paid readiness includes live tariff qualification and is intentionally separate.
            spec.validate_role(profile)
            if (
                profile["role"] != role
                or profile["plan"] != plan
                or profile["runtime"] != receipt.get("runtime")
            ):
                raise spec.ConfigurationError("FULL_EXISTING_ROLE_BINDING_CHANGED")
            if not role.startswith("paid_"):
                probe.check(profile)
        return receipt | {"state": "validated_existing", "provider_calls": 0}
    topology = plan["topology"]
    dsn = f"postgresql://postgres:{quote(value['owner_password'], safe='')}@{topology['postgres_host']}:{topology['postgres_port']}/postgres"
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as c:
        if c.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", ("tender_checks_" + plan["name"],)
        ).fetchone() or any((directory / "runtime").iterdir()):
            raise spec.ConfigurationError("FULL_PARTIAL_STATE_REFUSED")
        for group in spec.fresh.GROUPS:
            if c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (group,)).fetchone() is None:
                c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
    initialize_topics(kafka, policy, expected_cluster_id=plan["kafka_cluster_id"])
    initialize_store(value, marker=marker, create=True)
    base = directory / "base.env"
    spec.fresh.write_private(
        base,
        {"OWNER_DATABASE_DSN": dsn, "OBJECT_STORE_PREFIX": "fusion-full/" + plan["deployment_id"]},
    )
    receipt = spec.fresh.bootstrap(
        base_profile=base,
        name=plan["name"],
        extensions=[
            (spec.fresh.ROOT / item["path"], item["sha256"])
            for item in plan["ordered_sql"]
            if item["path"] in spec.EXTENSIONS
        ],
        assistant_budget_admin=True,
        app_origin=plan["origin"],
    )
    if receipt["ordered_sql"] != plan["ordered_sql"]:
        raise spec.ConfigurationError("FULL_BOOTSTRAP_PLAN_MISMATCH")
    business = file_configuration(spec.fresh.ROOT / receipt["profiles"]["business"])
    # Authentication hashing does not load provider configuration. Prevent an incidental .env read.
    os.environ["WORKBENCH_ENV_FILE"] = "explicit-fusion-full-initialization"
    from apps.api.auth import password_hash

    with psycopg.connect(business["API_DATABASE_DSN"]) as c:
        c.execute("SET LOCAL search_path=design,public")
        member = uuid4()
        c.execute("INSERT INTO members(id,display_name) VALUES(%s,'完整本机环境管理员')", (member,))
        c.execute(
            "INSERT INTO credentials(member_id,login_name,password_hash) VALUES(%s,'admin',%s)",
            (member, password_hash(value["admin_password"])),
        )
    ready_profiles = profiles(value, receipt, business, marker)
    for role, profile in ready_profiles.items():
        if not role.startswith("paid_"):
            probe.check(profile)
        destination = directory / "runtime" / role
        destination.mkdir(mode=0o700)
        spec.write_private(destination / "profile.json", profile)
        if runtime_uid is not None:
            os.chown(destination, runtime_uid, runtime_uid)
            os.chown(destination / "profile.json", runtime_uid, runtime_uid)
    api_state = directory / "application-state" / "api"
    api_state.mkdir(mode=0o700)
    if runtime_uid is not None:
        os.chown(api_state, runtime_uid, runtime_uid)
    result = {
        "version": spec.VERSION,
        "state": "created_fresh",
        "plan_digest": spec.digest(plan),
        "database": receipt["database"],
        "ordered_sql": receipt["ordered_sql"],
        "runtime": identity(),
        "runtime_roles": sorted(ready_profiles),
        "logins": receipt["logins"],
        "bootstrap_profiles": receipt["profiles"],
        "provider_calls": 0,
        "consumers_started": 0,
        "automatic_task_runner_started": False,
        "model_configuration_is_not_fee_authorization": True,
        "render_sandbox_configured": False,
        "rag_runtime_configured": False,
        "configured_ocr_runtime": False,
    }
    spec.write_private(receipt_path, result)
    return result


def main():
    os.umask(0o077)
    try:
        result = initialize(Path("/deployment"), runtime_uid=65532)
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, (spec.ConfigurationError, spec.fresh.BootstrapError))
            else "FULL_INITIALIZATION_FAILED_PRIVATE_DETAILS_SUPPRESSED"
        )
        raise SystemExit(code) from None
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "state",
                    "database",
                    "plan_digest",
                    "provider_calls",
                    "consumers_started",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
