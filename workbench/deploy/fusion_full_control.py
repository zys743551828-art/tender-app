"""Validate or explicitly operate the separate full local Compose project."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from deploy import fusion_full_spec as spec

COMPOSE = spec.fresh.ROOT / "deploy/compose.fusion-full.yaml"
COMPONENTS = {
    "api": "api",
    "relay": "relay",
    "reconcile": "reconcile",
    "worker-document": "document",
    "worker-export": "export",
    "worker-comparison": "comparison",
    "build-controller": "build-controller",
    "word-controller": "word-controller",
    "worker-review": "review",
    "worker-assistant": "assistant",
    "review-controller": "review-controller",
    "assistant-controller": "assistant-controller",
    "task-runner": "task-runner",
}
PAID = {"worker-review", "worker-assistant", "review-controller", "assistant-controller"}
SOURCE_MOUNTS = [
    "../packages:/workspace/packages:ro",
    "../apps/api:/workspace/apps/api:ro",
    "../apps/worker:/workspace/apps/worker:ro",
    ".:/workspace/deploy:ro",
    "../requirements.lock.txt:/workspace/requirements.lock.txt:ro",
    "../pyproject.toml:/workspace/pyproject.toml:ro",
]
_VARIABLE = re.compile(r"\$\{([A-Z_]+):\?[^}]+\}")


def _values(directory, plan):
    values = {}
    try:
        for line in spec.private_file(directory / "compose.env").decode().splitlines():
            key, separator, raw = line.partition("=")
            if not separator or key in values:
                raise ValueError
            values[key] = json.loads(raw)
    except (ValueError, UnicodeError):
        raise spec.ConfigurationError("FULL_COMPOSE_VARIABLES_INVALID") from None
    expected = {
        "COMPOSE_PROJECT_NAME": "tender-"
        + plan["name"].replace("_", "-")
        + "-"
        + plan["deployment_id"][:12],
        "FUSION_FULL_DIRECTORY": str(directory),
        "FUSION_FULL_PYTHON_IMAGE": plan["images"]["python"],
        "FUSION_FULL_WEB_IMAGE": plan["images"]["web"],
        "FUSION_FULL_PORT": plan["origin"].rsplit(":", 1)[1],
        "FUSION_FULL_CLUSTER_ID": plan["kafka_cluster_id"],
    }
    if values != expected:
        raise spec.ConfigurationError("FULL_COMPOSE_VARIABLE_BINDING_CHANGED")
    return values


def structure(document, *, plan, directory):
    """Check isolation properties after YAML aliases and declared substitutions resolve."""
    services = document["services"]
    if set(services) != {"postgres", "kafka", "object-store", "init", "web", *COMPONENTS}:
        raise spec.ConfigurationError("FULL_COMPOSE_SERVICES_CHANGED")
    if document["networks"] != {
        "core": {"internal": True},
        "preview": {"driver": "bridge"},
        "model_egress": {"driver": "bridge"},
    }:
        raise spec.ConfigurationError("FULL_COMPOSE_NETWORKS_CHANGED")
    for name, service in services.items():
        image_key = (
            "object_store"
            if name == "object-store"
            else name
            if name in {"postgres", "kafka", "web"}
            else "python"
        )
        if (
            service["image"] != plan["images"][image_key]
            or service.get("pull_policy") != "never"
            or service.get("restart") != "no"
        ):
            raise spec.ConfigurationError("FULL_COMPOSE_IMAGE_OR_RESTART_CHANGED")
        if (
            service.get("privileged")
            or service.get("network_mode")
            or service.get("pid")
            or service.get("ipc")
            or service.get("env_file")
        ):
            raise spec.ConfigurationError("FULL_COMPOSE_PRIVILEGE_OR_ENV_FORBIDDEN")
        if "docker.sock" in str(service.get("volumes", [])):
            raise spec.ConfigurationError("FULL_COMPOSE_DOCKER_SOCKET_FORBIDDEN")
        if name != "web" and service.get("ports"):
            raise spec.ConfigurationError("FULL_INFRASTRUCTURE_PORT_EXPOSED")
        networks = (
            ["core", "preview"]
            if name == "web"
            else ["core", "model_egress"]
            if name in {"worker-review", "worker-assistant"}
            else ["core"]
        )
        if service.get("networks") != networks:
            raise spec.ConfigurationError("FULL_COMPONENT_NETWORK_CHANGED")
        profiles = ["model"] if name in PAID else ["automation"] if name == "task-runner" else []
        if service.get("profiles", []) != profiles:
            raise spec.ConfigurationError("FULL_COMPONENT_OPT_IN_CHANGED")
        if name not in COMPONENTS:
            continue
        component = COMPONENTS[name]
        role = spec.COMMANDS[component][0]
        if service.get("command") != ["python", "-m", "deploy.fusion_full_runtime", component]:
            raise spec.ConfigurationError("FULL_COMPONENT_COMMAND_CHANGED")
        expected_profile = str(directory / "runtime" / role) + ":/runtime:ro"
        mounts = service["volumes"]
        private_mounts = [mount for mount in mounts if mount.startswith(str(directory) + "/")]
        expected_private = [expected_profile]
        if name == "api":
            expected_private.append(str(directory / "application-state/api") + ":/workspace/.local")
        if private_mounts != expected_private or service.get("secrets"):
            raise spec.ConfigurationError("FULL_COMPONENT_CREDENTIAL_MOUNT_CHANGED")
        if mounts != SOURCE_MOUNTS + expected_private:
            raise spec.ConfigurationError("FULL_COMPONENT_MOUNT_CHANGED")
        if any(not mount.endswith(":ro") for mount in mounts if mount not in expected_private):
            raise spec.ConfigurationError("FULL_SOURCE_MOUNT_NOT_READONLY")
        if (
            service.get("user") != "65532:65532"
            or service.get("cap_drop") != ["ALL"]
            or service.get("cap_add")
            or not service.get("read_only")
            or service.get("security_opt") != ["no-new-privileges:true"]
        ):
            raise spec.ConfigurationError("FULL_COMPONENT_PROCESS_ISOLATION_CHANGED")
        if service.get("environment") != {
            "PYTHONPATH": "/workspace",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "WORKBENCH_ENV_FILE": "explicit-fusion-full-no-inherited-profile",
        }:
            raise spec.ConfigurationError("FULL_COMPOSE_CREDENTIAL_ENV_FORBIDDEN")
        if service.get("depends_on") != {
            "init": {"condition": "service_completed_successfully"}
        } or not service.get("healthcheck"):
            raise spec.ConfigurationError("FULL_COMPONENT_READINESS_MISSING")
    if services["web"]["ports"] != ["127.0.0.1:" + plan["origin"].rsplit(":", 1)[1] + ":8080"]:
        raise spec.ConfigurationError("FULL_WEB_NOT_LOOPBACK")
    if (
        services["init"].get("cap_add") != ["CHOWN", "DAC_OVERRIDE"]
        or services["init"].get("user") != "0:0"
        or services["init"].get("cap_drop") != ["ALL"]
    ):
        raise spec.ConfigurationError("FULL_INITIALIZER_CAPABILITIES_CHANGED")
    web = services["web"]
    if (
        web.get("user") != "65532:65532"
        or web.get("cap_drop") != ["ALL"]
        or web.get("cap_add")
        or not web.get("read_only")
    ):
        raise spec.ConfigurationError("FULL_WEB_PROCESS_ISOLATION_CHANGED")
    if web.get("entrypoint") != [
        "nginx",
        "-c",
        "/etc/nginx/nginx.conf",
        "-e",
        "/dev/null",
        "-g",
        "daemon off;",
    ] or web.get("volumes") != [
        "../apps/web/dist:/usr/share/nginx/html:ro",
        "./nginx-fusion-full-main.conf:/etc/nginx/nginx.conf:ro",
        "./nginx-fusion-full.conf:/etc/nginx/conf.d/fusion-full-server.conf:ro",
    ]:
        raise spec.ConfigurationError("FULL_WEB_CONFIGURATION_CHANGED")
    return document


def validate(directory, *, model=False, automation=False):
    directory = Path(directory).absolute()
    plan = spec.load_private_json(directory / "plan.json")
    spec.validate_plan(plan, check_frontend=True)
    if plan["topology"]["mode"] != "compose":
        raise spec.ConfigurationError("FULL_COMPOSE_PROFILE_REQUIRED")
    if model and not plan["model_configured"]:
        raise spec.ConfigurationError("FULL_MODEL_PROFILE_REQUIRED")
    if automation and not plan["task_runner_enabled"]:
        raise spec.ConfigurationError("FULL_TASK_RUNNER_DISABLED")
    values = _values(directory, plan)
    raw = _VARIABLE.sub(lambda match: values[match.group(1)], COMPOSE.read_text())
    if "${" in raw:
        raise spec.ConfigurationError("FULL_COMPOSE_VARIABLE_UNRESOLVED")
    document = structure(yaml.safe_load(raw), plan=plan, directory=directory)
    selected = [
        name
        for name, service in document["services"].items()
        if not service.get("profiles")
        or model
        and service["profiles"] == ["model"]
        or automation
        and service["profiles"] == ["automation"]
    ]
    return {
        "version": spec.VERSION,
        "plan_digest": spec.digest(plan),
        "project": values["COMPOSE_PROJECT_NAME"],
        "selected_services": sorted(selected),
        "sql_count": len(plan["ordered_sql"]),
        "model_selected": model,
        "automation_selected": automation,
        "provider_calls": 0,
        "containers_started": 0,
        "docker_validation_performed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "up", "status", "down"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--automation", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(args.directory, model=args.model, automation=args.automation)
        if args.action == "validate":
            print(json.dumps(result, ensure_ascii=False))
            return
        docker = shutil.which("docker")
        if not docker:
            raise spec.ConfigurationError("FULL_DOCKER_NOT_AVAILABLE")
        command = [
            docker,
            "compose",
            "--env-file",
            str(args.directory.absolute() / "compose.env"),
            "--project-name",
            result["project"],
            "-f",
            str(COMPOSE),
        ]
        if args.model:
            command += ["--profile", "model"]
        if args.automation:
            command += ["--profile", "automation"]
        # Never inherit another daemon endpoint, Compose project, model key or owner DSN.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "HOME"}
        }
        subprocess.run([*command, "config", "--quiet"], env=environment, check=True, timeout=30)  # nosec B603
        action = (
            ["up", "-d"] if args.action == "up" else ["ps"] if args.action == "status" else ["down"]
        )
        subprocess.run([*command, *action], env=environment, check=True, timeout=180)  # nosec B603
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, spec.ConfigurationError)
            else "FULL_COMPOSE_OPERATION_FAILED_PRIVATE_DETAILS_SUPPRESSED"
        )
        raise SystemExit(code) from None


if __name__ == "__main__":
    main()
