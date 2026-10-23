"""Actual DB/S3/Kafka readiness checks. Never enqueue, generate, mutate a head or call a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
import psycopg
from botocore.config import Config
from confluent_kafka.admin import AdminClient
from psycopg.rows import dict_row

from deploy import fusion_full_spec as spec
from deploy.initialize_topics import initialize

REQUIRED_TABLES = (
    "design.bid_packages",
    "design.bid_package_rule_corrections",
    "design.bid_package_submission_bindings",
    "design.authoring_word_imports",
    "design.assistant_generation_batches",
    "design.word_intake_receipts",
)


def store_client(environment):
    return boto3.client(
        "s3",
        endpoint_url=environment["OBJECT_STORE_ENDPOINT"],
        aws_access_key_id=environment["OBJECT_STORE_ACCESS_KEY"],
        aws_secret_access_key=environment["OBJECT_STORE_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 0},
            request_checksum_calculation="when_required",
        ),
    )


def database(profile):
    environment, role = profile["environment"], profile["role"]
    key = "WORKER_DATABASE_DSN" if "WORKER_DATABASE_DSN" in environment else "API_DATABASE_DSN"
    group = "tender_worker" if key == "WORKER_DATABASE_DSN" else "tender_api"
    with psycopg.connect(environment[key], connect_timeout=4, row_factory=dict_row) as c:
        c.execute("SET TRANSACTION READ ONLY")
        c.execute("SET LOCAL statement_timeout='5s'")
        identity = c.execute(
            "SELECT current_user AS login,current_database() AS database"
        ).fetchone()
        flags = c.execute(
            "SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        memberships = c.execute(
            "SELECT r.rolname,m.admin_option FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE m.member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
        ).fetchall()
        owns = c.execute(
            "SELECT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN('pg_catalog','information_schema') AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)) AS owned"
        ).fetchone()
        if (
            identity != {"login": profile["login"], "database": profile["database"]}
            or flags is None
            or any(flags.values())
            or owns is None
            or owns["owned"]
            or memberships != [{"rolname": group, "admin_option": False}]
        ):
            raise spec.ConfigurationError("FULL_DATABASE_ROLE_NOT_ISOLATED")
        missing = c.execute(
            "SELECT name FROM unnest(%s::text[]) name WHERE to_regclass(name) IS NULL",
            (list(REQUIRED_TABLES),),
        ).fetchall()
        if missing:
            raise spec.ConfigurationError("FULL_REQUIRED_SCHEMA_MISSING")
        # A paid lane needs a current non-synthetic tariff; this only reads its retained identity.
        price_id = None
        if role.startswith("paid_"):
            price = c.execute(
                "SELECT id,source_kind,currency FROM design.assistant_price_versions WHERE provider='deepseek' AND model=%s AND valid_from<=clock_timestamp() AND valid_until>clock_timestamp() ORDER BY verified_at DESC,created_at DESC,id DESC LIMIT 1",
                (environment["DEEPSEEK_MODEL"],),
            ).fetchone()
            if not price or price["source_kind"] != "official_tariff_and_context_limit":
                raise spec.ConfigurationError("FULL_OFFICIAL_PRICE_REQUIRED")
            price_id = str(price["id"])
            budget = c.execute(
                "SELECT currency,limit_minor,window_from<=clock_timestamp() AND window_until>clock_timestamp() AS current FROM design.assistant_budget_versions WHERE scope='global' AND owner_key='assistant' ORDER BY revision DESC LIMIT 1"
            ).fetchone()
            if (
                not budget
                or not budget["current"]
                or budget["currency"] != price["currency"]
                or budget["limit_minor"] <= 0
            ):
                raise spec.ConfigurationError("FULL_GLOBAL_BUDGET_REQUIRED")
    return {
        "role": group,
        "nonowner": True,
        "schema_tables_verified": len(REQUIRED_TABLES),
        "price_id": price_id,
    }


def check(profile, *, check_sources=True):
    spec.validate_role(profile, check_sources=check_sources)
    result = {
        "version": spec.VERSION,
        "role": profile["role"],
        "plan_digest": profile["plan_digest"],
        "provider_calls": 0,
    }
    try:
        result["database"] = database(profile)
    except spec.ConfigurationError:
        raise
    except Exception:
        raise spec.ConfigurationError("FULL_DATABASE_UNAVAILABLE") from None
    environment = profile["environment"]
    if spec.STORE_KEYS <= set(environment):
        try:
            response = store_client(environment).get_object(
                Bucket=environment["OBJECT_STORE_BUCKET"], Key=profile["probe"]["key"]
            )
            with response["Body"] as stream:
                data = stream.read(profile["probe"]["byte_size"] + 1)
            if (
                len(data) != profile["probe"]["byte_size"]
                or spec.digest(data) != profile["probe"]["sha256"]
            ):
                raise spec.ConfigurationError("FULL_OBJECT_BINDING_MISMATCH")
        except spec.ConfigurationError:
            raise
        except Exception:
            raise spec.ConfigurationError("FULL_OBJECT_STORE_UNAVAILABLE") from None
        result["object_store"] = {
            "authenticated_get": True,
            "sha256_verified": True,
            "scope": "registered_runtime_probe_only",
        }
    if "KAFKA_BOOTSTRAP_SERVERS" in environment:
        try:
            policy = json.loads((spec.fresh.ROOT / spec.POLICY).read_bytes())
            result["kafka"] = initialize(
                AdminClient({"bootstrap.servers": environment["KAFKA_BOOTSTRAP_SERVERS"]}),
                policy,
                create_missing=False,
                expected_cluster_id=profile["plan"]["kafka_cluster_id"],
            )
        except Exception:
            raise spec.ConfigurationError("FULL_KAFKA_IDENTITY_OR_TOPICS_UNAVAILABLE") from None
    result["ready"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("/runtime/profile.json"))
    args = parser.parse_args()
    try:
        result = check(spec.load_private_json(args.profile))
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, spec.ConfigurationError)
            else "FULL_READINESS_FAILED_PRIVATE_DETAILS_SUPPRESSED"
        )
        raise SystemExit(code) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
