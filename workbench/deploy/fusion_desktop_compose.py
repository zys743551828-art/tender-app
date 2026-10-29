"""Compose desktop transport: POSIX private volumes, public host descriptor only."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml  # type: ignore[import-untyped]

from deploy import fusion_full_control as full
from deploy import fusion_full_spec as spec

VERSION = "fusion-desktop-full/1"
ROOT = spec.fresh.ROOT
ROLES = ("api", "worker", "relay", "reconcile", "controller")
PRIVATE = "/private/deployment"
BINDS = {
    "../packages",
    "../apps/api",
    "../apps/worker",
    "../apps/web/dist",
    ".",
    "../requirements.lock.txt",
    "../pyproject.toml",
    "./nginx-fusion-full-main.conf",
    "./nginx-fusion-full.conf",
}


def validate_request(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "instance_id", "name", "origin", "python_image", "web_image"}
        or value["version"] != VERSION
    ):
        raise spec.ConfigurationError("DESKTOP_REQUEST_INVALID")
    if (
        not isinstance(value["instance_id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", value["instance_id"])
        or not isinstance(value["name"], str)
        or not re.fullmatch(r"full_[a-z0-9_]{1,15}", value["name"])
        or not spec.pinned_image(value["python_image"])
        or not spec.pinned_image(value["web_image"])
    ):
        raise spec.ConfigurationError("DESKTOP_IDENTITY_INVALID")
    try:
        origin = urlsplit(value["origin"])
        valid = (
            origin.scheme == "http"
            and origin.hostname == "127.0.0.1"
            and (origin.port is not None and 1024 < origin.port < 65536)
            and not any(
                (origin.path, origin.query, origin.fragment, origin.username, origin.password)
            )
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise spec.ConfigurationError("DESKTOP_LOOPBACK_REQUIRED")
    return value


def project(value):
    validate_request(value)
    return "tender-fusion-full-" + value["instance_id"][:12]


def volume(name, target, *, readonly=False):
    return {"type": "volume", "source": name, "target": target, "read_only": readonly}


def bind(path, target, *, readonly=True):
    return {
        "type": "bind",
        "source": str(Path(path).resolve()),
        "target": target,
        "read_only": readonly,
    }


def _mount(raw):
    parts = raw.rsplit(":", 2)
    if len(parts) == 3:
        source, target, mode = parts
        if mode != "ro":
            raise spec.ConfigurationError("DESKTOP_SOURCE_WRITABLE")
        readonly = True
    else:
        source, target = raw.split(":", 1)
        readonly = False
    if source in {"postgres_data", "kafka_data", "object_data"}:
        return volume(source, target)
    if source == PRIVATE:
        return volume("private_config", "/private")
    if source == PRIVATE + "/state":
        return volume("init_state", target)
    if source == PRIVATE + "/application-state/api":
        return volume("api_state", target)
    if source.startswith(PRIVATE + "/runtime/"):
        role = source.removeprefix(PRIVATE + "/runtime/")
        if role not in spec.ROLE_KEYS or not readonly:
            raise spec.ConfigurationError("DESKTOP_ROLE_MOUNT_INVALID")
        return volume("profile_" + role, target, readonly=True)
    if source not in BINDS or not readonly:
        raise spec.ConfigurationError("DESKTOP_MOUNT_INVALID")
    return bind(ROOT / "deploy" / source, target)


def _base(request, cluster):
    values = {
        "COMPOSE_PROJECT_NAME": project(request),
        "FUSION_FULL_DIRECTORY": PRIVATE,
        "FUSION_FULL_PYTHON_IMAGE": request["python_image"],
        "FUSION_FULL_WEB_IMAGE": request["web_image"],
        "FUSION_FULL_PORT": str(urlsplit(request["origin"]).port),
        "FUSION_FULL_CLUSTER_ID": cluster,
    }
    return yaml.safe_load(
        full._VARIABLE.sub(lambda m: values[m.group(1)], full.COMPOSE.read_text())
    )


def _helper(template, request, directory, action):
    service = deepcopy(template)
    service["command"] = ["python", "-m", "deploy.fusion_desktop_private", action]
    service["depends_on"] = {}
    service["labels"] = {"tender.desktop.instance": request["instance_id"]}
    service["volumes"] = [
        bind(ROOT / "deploy" / source, target)
        for source, target in (
            ("../packages", "/workspace/packages"),
            ("../apps/api", "/workspace/apps/api"),
            ("../apps/worker", "/workspace/apps/worker"),
            ("../apps/web/dist", "/workspace/apps/web/dist"),
            (".", "/workspace/deploy"),
            ("../requirements.lock.txt", "/workspace/requirements.lock.txt"),
            ("../pyproject.toml", "/workspace/pyproject.toml"),
        )
    ]
    if action == "configure":
        service["volumes"] += [
            volume("private_config", "/private"),
            volume("owner_secret", "/owner-secret"),
            volume("store_secret", "/store-secret"),
            bind(directory, "/public", readonly=False),
        ]
    else:
        service["volumes"] += [volume("private_config", "/private", readonly=True)]
        service["volumes"] += [volume("profile_" + role, "/profiles/" + role) for role in ROLES]
        service["volumes"].append(volume("api_state", "/api-state"))
        service["volumes"].append(volume("validation_login", "/validation-login"))
    return service


def validate_public_plan(plan):
    reviewed = spec.ordered_sql()
    expected = [{"path": item.path.replace("\\", "/"), "sha256": item.sha256} for item in reviewed]
    if not isinstance(plan, dict) or plan.get("ordered_sql") != expected:
        raise spec.ConfigurationError("DESKTOP_PUBLIC_SQL_BINDING_CHANGED")
    # The private Linux plan stays intact. Only this validation copy uses the
    # host platform's spelling for exactly the same reviewed file paths.
    local = deepcopy(plan)
    local["ordered_sql"] = [{"path": item.path, "sha256": item.sha256} for item in reviewed]
    spec.validate_plan(local, check_sources=False)


def document(request, directory, plan=None):
    validate_request(request)
    cluster = "A" * 22 if plan is None else plan["kafka_cluster_id"]
    if plan is not None:
        validate_public_plan(plan)
        if (
            plan["name"] != request["name"]
            or plan["origin"] != request["origin"]
            or plan["images"]["python"] != request["python_image"]
            or plan["images"]["web"] != request["web_image"]
            or plan["model_configured"]
            or plan["task_runner_enabled"]
        ):
            raise spec.ConfigurationError("DESKTOP_PLAN_BINDING_CHANGED")
    result = _base(request, cluster)
    if plan is not None:
        full.structure(result, plan=plan, directory=PurePosixPath(PRIVATE))
    template = deepcopy(result["services"]["init"])
    configure = _helper(template, request, directory, "configure")
    volumes: dict[str, dict[str, object]] = {
        name: {}
        for name in (
            "private_config",
            "owner_secret",
            "store_secret",
            "init_state",
            "api_state",
            "validation_login",
            "postgres_data",
            "kafka_data",
            "object_data",
            *("profile_" + role for role in spec.ROLE_KEYS),
        )
    }
    result.pop("secrets", None)
    result["volumes"] = volumes
    if plan is None:
        result["services"] = {"configure": configure}
        return result
    services = result["services"]
    for name, service in services.items():
        service["labels"] = {"tender.desktop.instance": request["instance_id"]}
        service["volumes"] = [_mount(raw) for raw in service.get("volumes", [])]
        service.pop("secrets", None)
        if name in full.COMPONENTS:
            service["depends_on"] = {"publish": {"condition": "service_completed_successfully"}}
    for name in ("postgres", "kafka", "object-store"):
        services[name]["depends_on"] = {
            "configure": {"condition": "service_completed_successfully"}
        }
    services["postgres"]["volumes"].append(volume("owner_secret", "/run/secrets", readonly=True))
    services["object-store"]["volumes"].append(
        volume("store_secret", "/run/secrets", readonly=True)
    )
    services["init"]["command"] = ["python", "-m", "deploy.fusion_desktop_private", "initialize"]
    services["init"]["depends_on"]["configure"] = {"condition": "service_completed_successfully"}
    services["configure"] = configure
    services["publish"] = _helper(template, request, directory, "publish")
    services["publish"]["depends_on"] = {"init": {"condition": "service_completed_successfully"}}
    validation = deepcopy(template)
    validation["user"] = "65532:65532"
    validation.pop("cap_add", None)
    validation["command"] = ["python", "-m", "deploy.fusion_desktop_verify"]
    validation["profiles"] = ["checks"]
    validation["labels"] = {"tender.desktop.instance": request["instance_id"]}
    validation["depends_on"] = {"web": {"condition": "service_healthy"}}
    validation["volumes"] = [
        bind(ROOT / "deploy" / source, target)
        for source, target in (
            ("../packages", "/workspace/packages"),
            ("../apps/api", "/workspace/apps/api"),
            ("../apps/worker", "/workspace/apps/worker"),
            (".", "/workspace/deploy"),
            ("../requirements.lock.txt", "/workspace/requirements.lock.txt"),
            ("../pyproject.toml", "/workspace/pyproject.toml"),
        )
    ] + [
        volume("profile_api", "/runtime", readonly=True),
        volume("validation_login", "/validation-login", readonly=True),
    ]
    services["validation"] = validation
    return result


def validate_document(actual, request, directory, plan=None):
    if actual != document(request, directory, plan):
        raise spec.ConfigurationError("DESKTOP_COMPOSE_BINDING_CHANGED")
    return actual


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
