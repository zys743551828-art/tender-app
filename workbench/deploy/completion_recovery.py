"""Current-schema local recovery checks, separate from the frozen OSS protocol.

This module never starts a worker, resumes an old queue, accepts a business
database as a restore target, or confers production recovery qualification.
The opt-in test supplies a fresh PG cluster and an explicit synthetic loopback
S3 profile.  Database backup/restore uses the existing catalog implementation;
these helpers bind its database component to independently verified originals.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess  # nosec B404
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import boto3
from botocore.config import Config
from psycopg.conninfo import conninfo_to_dict

from deploy import bootstrap_fresh
from deploy.application_recovery import definition_equivalence
from deploy.backups import generic, run

# These are explicit optional capabilities, in dependency order.  Their presence
# does not enable a consumer, price configuration, paid model, or research use.
EXTENSIONS = (
    "packages/word_intake/schema.sql",
    "packages/knowledge/sql/rag.sql",
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
    "packages/assistant/sql/generation-batches.sql",
    "deploy/sql/model-governance.sql",
    "deploy/sql/historical-backtest.sql",
    "deploy/sql/model-governance-release.sql",
    "deploy/sql/historical-input-qualification.sql",
    "deploy/sql/score-execution.sql",
    "deploy/sql/technical-scale-authority.sql",
    "deploy/sql/score-denominator.sql",
    "deploy/sql/retrospective-research.sql",
)
REQUIRED_BASE = {
    "packages/identity/sql/stable-lot-identity.sql",
    "packages/authoring/sql/docx_import.sql",
    "packages/contracts/sql/bid-package-rule-corrections.sql",
    "packages/contracts/sql/bid-package-submissions.sql",
}
ORIGINALS_FORMAT = "completion-recovery-originals/1"
# Exact pg_dump/pg_restore CHECK reparse pairs observed on the current optional
# schemas. No values, operators, fields or unrecognized identities are normalized.
REPARSED_CHECKS = {
    ("score_execution", "current_chapters_raw_content_check", "current_chapters", ""): (
        definition_equivalence.NESTED,
        definition_equivalence.FLAT,
    ),
    ("technical_scale", "evidence_supported_fields_check", "evidence", ""): (
        "CHECK ((((cardinality(supported_fields) >= 1) AND (cardinality(supported_fields) <= 3)) AND (supported_fields <@ ARRAY['technical_maximum'::text, 'scale_description'::text, 'aggregation'::text])))",
        "CHECK (((cardinality(supported_fields) >= 1) AND (cardinality(supported_fields) <= 3) AND (supported_fields <@ ARRAY['technical_maximum'::text, 'scale_description'::text, 'aggregation'::text])))",
    ),
}


def normalized_definitions(value):
    result = definition_equivalence.canonical(value)
    for row in result.get("constraints", []):
        pair = REPARSED_CHECKS.get(tuple(row[:4]))
        if pair is not None and len(row) == 5 and row[4] in pair:
            row[4] = pair[1]
    return result


def equivalent_definitions(expected, actual):
    return normalized_definitions(expected) == normalized_definitions(actual)


def frozen_plan():
    """Freeze all actual SQL bytes before connecting or creating any resource."""
    if not REQUIRED_BASE <= set(bootstrap_fresh.BASE_SQL):
        raise run.BackupError("CURRENT_COMPLETION_BASE_REQUIRED")
    extensions = [
        bootstrap_fresh.reviewed_sql(bootstrap_fresh.ROOT / path)
        for path in EXTENSIONS
        if path not in bootstrap_fresh.BASE_SQL
    ]
    return bootstrap_fresh.sql_plan(
        [(bootstrap_fresh.ROOT / item.path, item.sha256) for item in extensions]
    )


def plan_receipt(plan):
    return [{"path": item.path, "sha256": item.sha256} for item in plan]


def local_pg_tool(binary_directory, _container, tool, dsn, args, **kwargs):
    """Same real PG tools, with credentials in a filtered environment, no shell."""
    if tool not in {"pg_dump", "pg_restore"}:
        raise run.BackupError("POSTGRES_TOOL_INVALID")
    binary_directory = Path(binary_directory).resolve()
    executable = binary_directory / tool
    fields = {key: str(value) for key, value in conninfo_to_dict(dsn).items() if value is not None}
    if (
        fields.get("host") != "127.0.0.1"
        or not fields.get("port", "").isdigit()
        or not 1024 < int(fields["port"]) < 65536
        or set(fields)
        - {"host", "port", "dbname", "user", "password", "options", "connect_timeout"}
        or not executable.is_file()
        or executable.is_symlink()
        or not fields.get("user")
        or not fields.get("dbname")
    ):
        raise run.BackupError("EXPLICIT_LOCAL_PG_TOOLS_REQUIRED")
    environment = {
        key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}
    }
    environment.update(
        PGHOST="127.0.0.1",
        PGPORT=fields["port"],
        PGDATABASE=fields["dbname"],
        PGUSER=fields["user"],
        PGPASSWORD=fields.get("password", ""),
        PGCONNECT_TIMEOUT="5",
    )
    result = subprocess.run(  # nosec B603
        [str(executable), *args],
        env=environment,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
        **kwargs,
    )
    if result.returncode:
        raise run.BackupError("LOCAL_POSTGRES_TOOL_FAILED_PRIVATE_DETAILS_SUPPRESSED")
    return result


def synthetic_s3(profile_path):
    """Use only an explicitly supplied loopback fixture, never discover accounts."""
    profile_path = Path(profile_path)
    profile = json.loads(profile_path.read_text())
    endpoint = urlsplit(profile.get("s3_endpoint", ""))
    if (
        profile.get("only_synthetic") is not True
        or endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or not endpoint.port
        or endpoint.username
        or endpoint.password
        or endpoint.path
        or endpoint.query
        or endpoint.fragment
    ):
        raise run.BackupError("EXPLICIT_SYNTHETIC_LOOPBACK_S3_REQUIRED")
    credentials = Path(profile["credentials_path"])
    if (
        credentials.is_symlink()
        or not credentials.is_file()
        or stat.S_IMODE(credentials.stat().st_mode) != 0o600
    ):
        raise run.BackupError("PRIVATE_SYNTHETIC_S3_CREDENTIALS_REQUIRED")
    identity = json.loads(credentials.read_text())["identities"][0]["credentials"][0]
    return {
        "endpoint": profile["s3_endpoint"],
        "access_key": identity["accessKey"],
        "secret_key": identity["secretKey"],
    }


def s3_client(configuration, *, wrong_secret=False):
    return boto3.client(
        "s3",
        endpoint_url=configuration["endpoint"],
        aws_access_key_id=configuration["access_key"],
        aws_secret_access_key=(
            "explicit-wrong-local-recovery-key" if wrong_secret else configuration["secret_key"]
        ),
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 0},
        ),
    )


def _private_file(path):
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise run.BackupError("COMPLETION_ORIGINAL_FILE_MISSING_OR_NOT_PRIVATE")
    return path


def archive_originals(directory, database_manifest, client, bucket):
    """Use exactly the exported DB references; never an independent live listing."""
    checked = generic.validate(directory)
    if checked != database_manifest or checked["objects_included"] is not False:
        raise run.BackupError("EXACT_DATABASE_COMPONENT_REQUIRED")
    if sum(item["bytes"] for item in checked["objects"]) > run.MAX_ARCHIVE_BYTES:
        raise run.BackupError("ARCHIVE_OBJECT_BUDGET_EXCEEDED")
    objects = []
    for item in checked["objects"]:
        identity = str(UUID(item["id"]))
        content = run.read_object(client, bucket, item["key"], item["bytes"], item["sha256"])
        filename = "objects/" + identity + ".bin"
        run.private_write(directory / filename, content)
        objects.append({**item, "file": filename})
    manifest = {
        "format": ORIGINALS_FORMAT,
        "database_manifest_sha256": generic.hash_file(directory / "manifest.json"),
        "database_sha256": checked["database_sha256"],
        "source_bucket": bucket,
        "transport": "real_loopback_s3_synthetic_only",
        "objects": objects,
        "native_oss_qualified": False,
        "full_application_restore_qualified": False,
    }
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
    run.private_write(directory / "originals.json", raw)
    run.private_write(directory / "originals.sha256", run.digest(raw).encode())
    return manifest


def validate_originals(directory):
    """Validate every byte before any target database or bucket is created."""
    database = generic.validate(directory)
    path = _private_file(directory / "originals.json")
    if path.stat().st_size > generic.MAX_MANIFEST_BYTES:
        raise run.BackupError("MANIFEST_BUDGET_EXCEEDED")
    raw = path.read_bytes()
    if run.digest(raw) != _private_file(directory / "originals.sha256").read_text():
        raise run.BackupError("COMPLETION_ORIGINAL_MANIFEST_CHANGED")
    value = json.loads(raw)
    if (
        value.get("format") != ORIGINALS_FORMAT
        or value.get("database_manifest_sha256") != generic.hash_file(directory / "manifest.json")
        or value.get("database_sha256") != database["database_sha256"]
        or value.get("transport") != "real_loopback_s3_synthetic_only"
        or value.get("native_oss_qualified") is not False
        or value.get("full_application_restore_qualified") is not False
        or [{k: v for k, v in item.items() if k != "file"} for item in value["objects"]]
        != database["objects"]
    ):
        raise run.BackupError("COMPLETION_ORIGINAL_DATABASE_BINDING_CHANGED")
    seen = set()
    for item in value["objects"]:
        identity = str(UUID(item["id"]))
        if item.get("file") != "objects/" + identity + ".bin" or identity in seen:
            raise run.BackupError("OBJECT_PATH_INVALID")
        seen.add(identity)
        path = _private_file(directory / item["file"])
        if path.stat().st_size != item["bytes"] or generic.hash_file(path) != item["sha256"]:
            raise run.BackupError("COMPLETION_ORIGINAL_BYTES_CHANGED")
    return value


def restore_originals(directory, client, target_bucket):
    """Caller owns the new, empty bucket; source namespace is never overwritten."""
    manifest = validate_originals(directory)
    if target_bucket == manifest["source_bucket"]:
        raise run.BackupError("COMPLETION_RESTORE_BUCKET_MUST_BE_DISTINCT")
    if client.list_objects_v2(Bucket=target_bucket, MaxKeys=1).get("Contents"):
        raise run.BackupError("COMPLETION_RESTORE_BUCKET_MUST_BE_EMPTY")
    for item in manifest["objects"]:
        client.put_object(
            Bucket=target_bucket,
            Key=item["key"],
            Body=(directory / item["file"]).read_bytes(),
            ContentType=item["media_type"],
        )
        run.read_object(client, target_bucket, item["key"], item["bytes"], item["sha256"])
    return len(manifest["objects"])
