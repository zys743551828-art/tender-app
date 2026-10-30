"""Read-only checks for isolated external-provider development infrastructure."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from initialize_database import ROOT, file_configuration
from initialize_topics import verify_implemented_topics


def check(path: Path) -> dict:
    values = file_configuration(path)
    if values.get("COMPOSE_PROJECT_NAME") != "tender-workbench-external":
        raise ValueError("Not the external environment profile")
    if path.stat().st_mode & 0o077:
        raise ValueError("External profile must be private")
    if values.get("KAFKA_BOOTSTRAP_SERVERS") != "127.0.0.1:19095":
        raise ValueError("Kafka must be the independent external broker")
    roles = []
    database_name = values.get("WORKBENCH_DATABASE_NAME", "tender")
    if database_name not in ("tender", "tender_release"):
        raise ValueError("Unexpected isolated database name")
    for role in ("api", "worker", "research_worker", "score_read"):
        dsn = values[f"{role.upper()}_DATABASE_DSN"]
        target = urlsplit(dsn)
        if (
            target.hostname != "127.0.0.1"
            or target.port != 55441
            or target.path != "/" + database_name
        ):
            raise ValueError("External database profile aliases another environment")
        with psycopg.connect(dsn) as connection:
            record = connection.execute(
                """SELECT r.rolsuper,r.rolcreaterole,r.rolcreatedb,
                   pg_has_role(current_user,%s,'MEMBER'),
                   EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname IN ('design','retrieval')
                   AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))
                   FROM pg_roles r WHERE r.rolname=current_user""",
                (f"tender_{role}",),
            ).fetchone()
            if not record or any(record[:3]) or not record[3] or record[4]:
                raise ValueError("External runtime role violates nonowner capability boundary")
            roles.append({"capability": role, "nonowner_login": True})
    kafka = verify_implemented_topics(values["KAFKA_BOOTSTRAP_SERVERS"])
    topics = [{"name": name, "partitions": 6} for name in kafka["topic_names"]]
    prefix = values.get("OBJECT_STORE_PREFIX", "")
    if (
        values.get("OBJECT_STORE_BACKEND") != "oss"
        or not prefix.startswith("workbench-environments/")
        or not prefix.endswith("/")
    ):
        raise ValueError("External object storage must use its own native OSS namespace")
    return {
        "passed": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated local PG/Kafka and private external profile; no business acceptance",
        "postgres_port": 55441,
        "database_name": database_name,
        "kafka_port": 19095,
        "roles": roles,
        "topics": topics,
        "kafka": kafka,
        "object_store_backend": "oss",
        "object_namespace_isolated": True,
        "bucket_configuration_mutations": 0,
        "existing_environment_configuration_modified": False,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".local/external.env")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = check(arguments.env_file)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "roles": len(result["roles"]),
                "topics": len(result["topics"]),
            }
        )
    )


if __name__ == "__main__":
    main()
