"""Closed local application deployment identities; no connection or process startup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.conninfo import conninfo_to_dict

from deploy import bootstrap_fresh as fresh

VERSION = "fusion-full-local/1"
POLICY = "apps/worker/execution-policy-10.json"
EXTENSIONS = (
    "packages/word_intake/schema.sql",
    "packages/knowledge/sql/rag.sql",
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
    "packages/assistant/sql/generation-batches.sql",
)
IMAGES = {
    "postgres": "pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d",
    "kafka": "apache/kafka@sha256:5cc2a2fd93fa2687b44015eee04fb2c3edd9e526bd64bf8bec5ff1e268772e0e",
    "object_store": "chrislusf/seaweedfs@sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e",
}
MODEL_KEYS = frozenset({"DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"})
STORE_KEYS = frozenset(
    {
        "OBJECT_STORE_BACKEND",
        "OBJECT_STORE_ENDPOINT",
        "OBJECT_STORE_ACCESS_KEY",
        "OBJECT_STORE_SECRET_KEY",
        "OBJECT_STORE_BUCKET",
        "OBJECT_STORE_PREFIX",
        "OBJECT_STORE_REGION",
    }
)
FEATURE_KEYS = {"WORD_INTAKE_ENABLED"}
ROLE_KEYS = {
    "api": {
        "API_DATABASE_DSN",
        "APP_ORIGIN",
        "SESSION_SECRET",
        "CSRF_SECRET",
        "OBJECT_TRANSFER_MODE",
    }
    | STORE_KEYS
    | FEATURE_KEYS,
    "worker": {"WORKER_DATABASE_DSN", "KAFKA_BOOTSTRAP_SERVERS"} | STORE_KEYS | FEATURE_KEYS,
    "relay": {"WORKER_DATABASE_DSN", "KAFKA_BOOTSTRAP_SERVERS"},
    "reconcile": {"WORKER_DATABASE_DSN"},
    "controller": {"API_DATABASE_DSN"} | STORE_KEYS | FEATURE_KEYS,
    "paid_worker": {"WORKER_DATABASE_DSN", "KAFKA_BOOTSTRAP_SERVERS"}
    | STORE_KEYS
    | FEATURE_KEYS
    | MODEL_KEYS,
    "paid_controller": {"API_DATABASE_DSN"} | STORE_KEYS | FEATURE_KEYS | MODEL_KEYS,
    "task_runner": {"API_DATABASE_DSN"} | STORE_KEYS | FEATURE_KEYS,
}
COMMANDS = {
    "api": (
        "api",
        ("uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"),  # nosec B104
    ),
    "document": ("worker", ("apps.worker", "consume")),
    "export": ("worker", ("apps.worker", "consume-export")),
    "comparison": ("worker", ("apps.worker", "consume-comparison")),
    "relay": ("relay", ("apps.worker", "relay")),
    "reconcile": ("reconcile", ("apps.worker", "reconcile")),
    "build-controller": ("controller", ("apps.api.build_coordinator",)),
    "word-controller": ("controller", ("apps.api.word_coordinator",)),
    "review": ("paid_worker", ("apps.worker", "consume-review")),
    "assistant": ("paid_worker", ("apps.worker", "consume-assistant")),
    "review-controller": ("paid_controller", ("apps.api.review_coordinator",)),
    "assistant-controller": ("controller", ("packages.assistant.coordinator",)),
    "task-runner": ("task_runner", ("packages.tasks.runner",)),
}


class ConfigurationError(Exception):
    """Fixed public code only; never include a connection string or private input."""


def digest(value):
    data = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    return hashlib.sha256(data).hexdigest()


def private_file(path, *, limit=16 * 1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("FULL_PROFILE_PRIVATE_FILE_REQUIRED")
    info = path.stat()
    if stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= limit:
        raise ConfigurationError("FULL_PROFILE_PRIVATE_FILE_REQUIRED")
    return path.read_bytes()


def load_private_json(path):
    try:
        return json.loads(private_file(path))
    except (ValueError, UnicodeError):
        raise ConfigurationError("FULL_PROFILE_JSON_INVALID") from None


def write_private(path, data):
    path = Path(path)
    encoded = (
        data
        if isinstance(data, bytes)
        else (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    )
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as handle:
        handle.write(encoded)


def pinned_image(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[a-f0-9]{64}", value) is not None
    )


def ordered_sql():
    return fresh.sql_plan(
        [(fresh.ROOT / name, fresh.reviewed_sql(fresh.ROOT / name).sha256) for name in EXTENSIONS]
    )


def sources(root=None):
    root = Path(root or fresh.ROOT)
    selected = {}
    for directory in ("packages", "apps/api", "apps/worker", "deploy"):
        for path in sorted((root / directory).rglob("*")):
            relative = path.relative_to(root)
            if any(
                part in {"qa", "__pycache__", "application_recovery", "backups"}
                or part.startswith(".")
                for part in relative.parts
            ):
                continue
            if path.suffix not in {".py", ".sql", ".json", ".yaml", ".conf", ".gz"}:
                continue
            if path.is_symlink() or not path.is_file():
                raise ConfigurationError("FULL_RUNTIME_SOURCE_INVALID")
            selected[str(relative)] = digest(path.read_bytes())
    for name in ("requirements.lock.txt", "pyproject.toml", "deploy/fusion_full_requirements.txt"):
        selected[name] = digest((root / name).read_bytes())
    if not selected or len(selected) > 5000:
        raise ConfigurationError("FULL_RUNTIME_SOURCE_LIMIT")
    return selected


def frontend(root=None):
    root = Path(root or fresh.ROOT) / "apps/web/dist"
    if not (root / "index.html").is_file():
        raise ConfigurationError("FULL_FRONTEND_BUILD_REQUIRED")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ConfigurationError("FULL_FRONTEND_SYMLINK_FORBIDDEN")
        if path.is_file():
            result[str(path.relative_to(root))] = digest(path.read_bytes())
    return result


def validate_model(values):
    if values is None:
        return
    if not isinstance(values, dict) or set(values) != MODEL_KEYS:
        raise ConfigurationError("FULL_MODEL_PROFILE_KEYS_INVALID")
    # Match the closed production port without importing domain.runtime (which may
    # otherwise load an unrelated .env in an operator's configuration process).
    if (
        any(
            not isinstance(value, str) or not value.strip() or any(c in value for c in "\n\r\x00")
            for value in values.values()
        )
        or values["DEEPSEEK_MODEL"] not in {"deepseek-flash", "deepseek-v4-pro"}
        or values["DEEPSEEK_BASE_URL"]
        not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
    ):
        raise ConfigurationError("FULL_MODEL_PROFILE_INVALID")


def validate_topology(topology):
    if not isinstance(topology, dict) or set(topology) != {
        "mode",
        "postgres_host",
        "postgres_port",
        "kafka_bootstrap",
        "s3_endpoint",
    }:
        raise ConfigurationError("FULL_TOPOLOGY_INVALID")
    if topology["mode"] == "compose":
        if topology != {
            "mode": "compose",
            "postgres_host": "postgres",
            "postgres_port": 5432,
            "kafka_bootstrap": "kafka:9092",
            "s3_endpoint": "http://object-store:8333",
        }:
            raise ConfigurationError("FULL_COMPOSE_TOPOLOGY_INVALID")
    elif topology["mode"] == "loopback":
        try:
            endpoint = urlsplit(topology["s3_endpoint"])
            valid = (
                topology["postgres_host"] == "127.0.0.1"
                and type(topology["postgres_port"]) is int
                and 1024 < topology["postgres_port"] < 65536
                and re.fullmatch(r"127\.0\.0\.1:[0-9]{4,5}", topology["kafka_bootstrap"])
                and 1024 < int(topology["kafka_bootstrap"].split(":")[1]) < 65536
                and endpoint.scheme == "http"
                and endpoint.hostname == "127.0.0.1"
                and endpoint.port is not None
                and 1024 < endpoint.port < 65536
                and not any(
                    (
                        endpoint.path,
                        endpoint.username,
                        endpoint.password,
                        endpoint.query,
                        endpoint.fragment,
                    )
                )
            )
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ConfigurationError("FULL_LOOPBACK_TOPOLOGY_INVALID")
    else:
        raise ConfigurationError("FULL_LOCAL_TOPOLOGY_REQUIRED")


def validate_plan(plan, *, check_sources=True, check_frontend=False):
    keys = {
        "version",
        "deployment_id",
        "name",
        "origin",
        "images",
        "topology",
        "kafka_cluster_id",
        "bucket",
        "ordered_sql",
        "sources",
        "frontend",
        "policy_sha256",
        "model_configured",
        "task_runner_enabled",
    }
    if not isinstance(plan, dict) or set(plan) != keys or plan["version"] != VERSION:
        raise ConfigurationError("FULL_PLAN_SHAPE_INVALID")
    if (
        not isinstance(plan["deployment_id"], str)
        or not isinstance(plan["name"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", plan["deployment_id"])
        or not re.fullmatch(r"full_[a-z0-9_]{1,15}", plan["name"])
    ):
        raise ConfigurationError("FULL_PLAN_IDENTITY_INVALID")
    try:
        origin = urlsplit(plan["origin"])
        valid = (
            origin.scheme == "http"
            and origin.hostname == "127.0.0.1"
            and origin.port is not None
            and 1024 < origin.port < 65536
            and not any(
                (origin.path, origin.username, origin.password, origin.query, origin.fragment)
            )
        )
    except (ValueError, TypeError):
        valid = False
    if (
        not valid
        or not isinstance(plan["kafka_cluster_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{22}", plan["kafka_cluster_id"])
    ):
        raise ConfigurationError("FULL_ORIGIN_OR_CLUSTER_INVALID")
    if (
        not isinstance(plan["bucket"], str)
        or plan["bucket"] != "fusion-full-" + plan["deployment_id"]
    ):
        raise ConfigurationError("FULL_BUCKET_IDENTITY_INVALID")
    if type(plan["model_configured"]) is not bool or type(plan["task_runner_enabled"]) is not bool:
        raise ConfigurationError("FULL_FEATURE_FLAGS_INVALID")
    if (
        not isinstance(plan["images"], dict)
        or set(plan["images"]) != {*IMAGES, "python", "web"}
        or any(not pinned_image(value) for value in plan["images"].values())
    ):
        raise ConfigurationError("FULL_PINNED_IMAGES_REQUIRED")
    if any(plan["images"][key] != value for key, value in IMAGES.items()):
        raise ConfigurationError("FULL_INFRASTRUCTURE_IMAGE_CHANGED")
    validate_topology(plan["topology"])
    actual_sql = [{"path": item.path, "sha256": item.sha256} for item in ordered_sql()]
    if plan["ordered_sql"] != actual_sql or plan["policy_sha256"] != digest(
        (fresh.ROOT / POLICY).read_bytes()
    ):
        raise ConfigurationError("FULL_SCHEMA_OR_POLICY_CHANGED")
    if check_sources and plan["sources"] != sources():
        raise ConfigurationError("FULL_RUNTIME_SOURCE_CHANGED")
    if check_frontend and plan["frontend"] != frontend():
        raise ConfigurationError("FULL_FRONTEND_BUILD_CHANGED")


def validate_role(profile, *, check_sources=True):
    if not isinstance(profile, dict) or set(profile) != {
        "version",
        "role",
        "plan",
        "plan_digest",
        "database",
        "login",
        "environment",
        "probe",
        "runtime",
    }:
        raise ConfigurationError("FULL_ROLE_PROFILE_SHAPE_INVALID")
    role, plan, environment = profile["role"], profile["plan"], profile["environment"]
    if (
        profile["version"] != VERSION
        or not isinstance(role, str)
        or role not in ROLE_KEYS
        or profile["plan_digest"] != digest(plan)
    ):
        raise ConfigurationError("FULL_ROLE_PROFILE_BINDING_INVALID")
    validate_plan(plan, check_sources=check_sources)
    allowed = ROLE_KEYS[role] | (
        MODEL_KEYS if role in {"api", "task_runner"} and plan["model_configured"] else set()
    )
    if (
        not isinstance(environment, dict)
        or set(environment) != allowed
        or any(
            not isinstance(value, str) or not value or "\x00" in value or "\n" in value
            for value in environment.values()
        )
    ):
        raise ConfigurationError("FULL_ROLE_ENVIRONMENT_INVALID")
    if role.startswith("paid_") and not plan["model_configured"]:
        raise ConfigurationError("FULL_MODEL_PROFILE_REQUIRED")
    if role == "task_runner" and not plan["task_runner_enabled"]:
        raise ConfigurationError("FULL_TASK_RUNNER_DISABLED")
    if MODEL_KEYS <= set(environment):
        validate_model({key: environment[key] for key in MODEL_KEYS})
    if FEATURE_KEYS <= set(environment) and environment["WORD_INTAKE_ENABLED"] != "1":
        raise ConfigurationError("FULL_WORD_INTAKE_CONFIGURATION_CHANGED")
    try:
        key = "WORKER_DATABASE_DSN" if "WORKER_DATABASE_DSN" in allowed else "API_DATABASE_DSN"
        db = conninfo_to_dict(environment[key])
    except Exception:
        raise ConfigurationError("FULL_DATABASE_PROFILE_INVALID") from None
    expected = plan["topology"]
    if (
        set(db) != {"host", "port", "dbname", "user", "password"}
        or db["host"] != expected["postgres_host"]
        or str(db["port"]) != str(expected["postgres_port"])
        or db["dbname"] != profile["database"]
        or db["user"] != profile["login"]
        or profile["database"] != "tender_checks_" + plan["name"]
        or not isinstance(profile["login"], str)
        or not re.fullmatch(r"twb_checks_[a-z0-9_]+_(api|worker)", profile["login"])
    ):
        raise ConfigurationError("FULL_DATABASE_IDENTITY_MISMATCH")
    if (
        "KAFKA_BOOTSTRAP_SERVERS" in environment
        and environment["KAFKA_BOOTSTRAP_SERVERS"] != expected["kafka_bootstrap"]
    ):
        raise ConfigurationError("FULL_KAFKA_ADDRESS_MISMATCH")
    if STORE_KEYS <= set(environment) and (
        environment["OBJECT_STORE_BACKEND"] != "s3"
        or environment["OBJECT_STORE_ENDPOINT"] != expected["s3_endpoint"]
        or environment["OBJECT_STORE_BUCKET"] != plan["bucket"]
        or environment["OBJECT_STORE_REGION"] != "us-east-1"
        or not environment["OBJECT_STORE_PREFIX"].startswith(
            "fusion-full/" + plan["deployment_id"] + "/check-environments/"
        )
    ):
        raise ConfigurationError("FULL_STORE_IDENTITY_MISMATCH")
    if role == "api" and (
        environment["APP_ORIGIN"] != plan["origin"]
        or environment["OBJECT_TRANSFER_MODE"] != "same_origin"
    ):
        raise ConfigurationError("FULL_API_ORIGIN_MISMATCH")
    probe = profile["probe"]
    if (
        not isinstance(probe, dict)
        or set(probe) != {"key", "sha256", "byte_size"}
        or probe["key"] != "runtime-binding/" + plan["deployment_id"] + ".json"
        or not isinstance(probe["sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", probe["sha256"])
        or type(probe["byte_size"]) is not int
        or not 0 < probe["byte_size"] < 1024 * 1024
    ):
        raise ConfigurationError("FULL_PROBE_BINDING_INVALID")
    from deploy.fusion_full_dependencies import identity

    if profile["runtime"] != identity():
        raise ConfigurationError("FULL_RUNTIME_DEPENDENCY_IDENTITY_CHANGED")
    return profile
