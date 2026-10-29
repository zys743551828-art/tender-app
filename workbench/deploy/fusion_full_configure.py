"""Prepare one explicit private full-runtime directory; never start Docker or a model."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

from deploy import fusion_full_spec as spec


def configure(
    directory,
    *,
    name,
    origin,
    python_image,
    web_image,
    admin_password,
    model=None,
    task_runner=False,
    topology=None,
):
    directory = Path(directory).absolute()
    if (
        directory.exists()
        or directory.is_symlink()
        or any(character in str(directory) for character in " \t\n\r:$#{}[]\\\"'")
    ):
        raise spec.ConfigurationError("FULL_NEW_PRIVATE_DIRECTORY_REQUIRED")
    if (
        not isinstance(admin_password, str)
        or len(admin_password) < 8
        or any(character in admin_password for character in "\n\r\x00")
    ):
        raise spec.ConfigurationError("FULL_ADMIN_PASSWORD_REQUIRED")
    spec.validate_model(model)
    identity = uuid4().hex
    plan = {
        "version": spec.VERSION,
        "deployment_id": identity,
        "name": name,
        "origin": origin,
        "images": {**spec.IMAGES, "python": python_image, "web": web_image},
        "topology": topology
        or {
            "mode": "compose",
            "postgres_host": "postgres",
            "postgres_port": 5432,
            "kafka_bootstrap": "kafka:9092",
            "s3_endpoint": "http://object-store:8333",
        },
        "kafka_cluster_id": secrets.token_urlsafe(16),
        "bucket": "fusion-full-" + identity,
        "ordered_sql": [{"path": item.path, "sha256": item.sha256} for item in spec.ordered_sql()],
        "sources": spec.sources(),
        "frontend": spec.frontend(),
        "policy_sha256": spec.digest((spec.fresh.ROOT / spec.POLICY).read_bytes()),
        "model_configured": model is not None,
        "task_runner_enabled": task_runner,
    }
    spec.validate_plan(plan)
    actors = {
        name: {
            "access_key": "full-" + name + "-" + secrets.token_hex(8),
            "secret_key": secrets.token_urlsafe(32),
        }
        for name in ("init", "api", "worker")
    }
    identities = {
        "identities": [
            {
                "name": "fusion-full-" + name,
                "credentials": [
                    {"accessKey": actor["access_key"], "secretKey": actor["secret_key"]}
                ],
                "actions": ["Admin", "Read", "Write", "List"]
                if name == "init"
                else [verb + ":" + plan["bucket"] for verb in ("Read", "Write", "List")],
            }
            for name, actor in actors.items()
        ]
    }
    owner_password = secrets.token_urlsafe(40)
    operator = {
        "plan": plan,
        "plan_digest": spec.digest(plan),
        "owner_password": owner_password,
        "admin_password": admin_password,
        "store_credentials": actors,
        "session_secret": secrets.token_urlsafe(48),
        "csrf_secret": secrets.token_urlsafe(48),
        "model": model,
    }
    directory.mkdir(mode=0o700, parents=True)
    directory.chmod(0o700)
    for part in ("state", "runtime", "application-state"):
        (directory / part).mkdir(mode=0o700)
    spec.write_private(directory / "operator.json", operator)
    spec.write_private(directory / "plan.json", plan)
    spec.write_private(directory / "owner-password", owner_password.encode())
    spec.write_private(directory / "s3-identities.json", identities)
    values = {
        "COMPOSE_PROJECT_NAME": "tender-" + name.replace("_", "-") + "-" + identity[:12],
        "FUSION_FULL_DIRECTORY": str(directory),
        "FUSION_FULL_PYTHON_IMAGE": python_image,
        "FUSION_FULL_WEB_IMAGE": web_image,
        "FUSION_FULL_PORT": origin.rsplit(":", 1)[1],
        "FUSION_FULL_CLUSTER_ID": plan["kafka_cluster_id"],
    }
    # This file contains paths/images/public identities only; no credential is expanded by Compose.
    spec.write_private(
        directory / "compose.env",
        ("".join(key + "=" + json.dumps(value) + "\n" for key, value in values.items())).encode(),
    )
    return {
        "directory": str(directory),
        "plan_digest": spec.digest(plan),
        "sql_count": len(plan["ordered_sql"]),
        "model_configured": plan["model_configured"],
        "task_runner_enabled": task_runner,
        "services_started": 0,
        "provider_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--name", required=True, help="New full_[a-z0-9_] environment name, maximum 20 characters"
    )
    parser.add_argument("--origin", default="http://127.0.0.1:5189")
    parser.add_argument(
        "--python-image",
        required=True,
        help="Already-built Python dependency image, repository@sha256:digest",
    )
    parser.add_argument(
        "--web-image", required=True, help="Already-built nginx image, repository@sha256:digest"
    )
    parser.add_argument("--admin-password-file", type=Path, required=True)
    parser.add_argument(
        "--model-profile",
        type=Path,
        help="Explicit private JSON with the three DEEPSEEK keys; does not authorize a call",
    )
    parser.add_argument(
        "--enable-task-runner",
        action="store_true",
        help="Permit the separately selected automation profile; creates no task/template",
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        value = configure(
            args.directory,
            name=args.name,
            origin=args.origin,
            python_image=args.python_image,
            web_image=args.web_image,
            admin_password=spec.private_file(args.admin_password_file, limit=4096)
            .decode()
            .rstrip("\r\n"),
            model=spec.load_private_json(args.model_profile) if args.model_profile else None,
            task_runner=args.enable_task_runner,
        )
    except (spec.ConfigurationError, OSError, ValueError) as error:
        code = (
            str(error)
            if isinstance(error, spec.ConfigurationError)
            else "FULL_CONFIGURATION_FAILED"
        )
        raise SystemExit(code) from None
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
