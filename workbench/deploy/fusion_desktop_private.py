"""Linux Compose setup stages; private values remain in dedicated volumes."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
from pathlib import Path

from deploy import fusion_desktop_compose as desktop
from deploy import fusion_full_spec as spec

PRIVATE = Path(desktop.PRIVATE)
PUBLIC = Path("/public")
UID = 65532


def _binding():
    from deploy import fusion_full_init as initialize

    value = initialize.operator(PRIVATE)
    binding = spec.load_private_json(PRIVATE / "desktop-binding.json")
    if not isinstance(binding, dict) or set(binding) != {"request", "plan_digest"}:
        raise spec.ConfigurationError("DESKTOP_PRIVATE_BINDING_INVALID")
    request = desktop.validate_request(binding["request"])
    plan = value["plan"]
    if (
        binding["plan_digest"] != value["plan_digest"]
        or plan["name"] != request["name"]
        or plan["origin"] != request["origin"]
        or plan["images"]["python"] != request["python_image"]
        or plan["images"]["web"] != request["web_image"]
        or plan["model_configured"]
        or plan["task_runner_enabled"]
    ):
        raise spec.ConfigurationError("DESKTOP_PRIVATE_BINDING_CHANGED")
    return value, binding


def _secret(directory, name, raw):
    path = directory / name
    if directory.is_symlink() or not directory.is_dir():
        raise spec.ConfigurationError("DESKTOP_SECRET_VOLUME_REQUIRED")
    if path.exists():
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o444
            or path.read_bytes() != raw
        ):
            raise spec.ConfigurationError("DESKTOP_SECRET_BINDING_CHANGED")
    else:
        if any(directory.iterdir()):
            raise spec.ConfigurationError("DESKTOP_SECRET_PARTIAL_STATE")
        spec.write_private(path, raw)
        path.chmod(0o444)


def configure():
    from deploy.fusion_full_configure import configure as create
    from deploy.fusion_full_dependencies import identity

    request = desktop.validate_request(json.loads((PUBLIC / "request.json").read_bytes()))
    identity()
    parent = PRIVATE.parent
    if parent.is_symlink() or not parent.is_dir():
        raise spec.ConfigurationError("DESKTOP_PRIVATE_VOLUME_REQUIRED")
    parent.chmod(0o700)
    if PRIVATE.exists():
        value, binding = _binding()
        if binding["request"] != request:
            raise spec.ConfigurationError("DESKTOP_REQUEST_CHANGED")
    else:
        create(
            PRIVATE,
            name=request["name"],
            origin=request["origin"],
            python_image=request["python_image"],
            web_image=request["web_image"],
            admin_password=secrets.token_urlsafe(32),
        )
        value = spec.load_private_json(PRIVATE / "operator.json")
        spec.write_private(
            PRIVATE / "desktop-binding.json",
            {"request": request, "plan_digest": value["plan_digest"]},
        )
        value, _ = _binding()
    _secret(Path("/owner-secret"), "owner_password", (PRIVATE / "owner-password").read_bytes())
    _secret(
        Path("/store-secret"), "s3-identities.json", (PRIVATE / "s3-identities.json").read_bytes()
    )
    raw = desktop.encoded(value["plan"])
    public = PUBLIC / "public-plan.json"
    if public.exists() and public.read_bytes() != raw:
        raise spec.ConfigurationError("DESKTOP_PUBLIC_PLAN_CHANGED")
    if not public.exists():
        with public.open("xb") as handle:
            handle.write(raw)
    return {
        "stage": "configured",
        "plan_digest": value["plan_digest"],
        "private_values_exported": False,
    }


def initialize():
    from deploy.fusion_full_init import initialize as create

    _binding()
    _initial_state(Path("/workspace/.local"))
    receipt = create(PRIVATE, runtime_uid=UID)
    return {
        "stage": "initialized",
        "database": receipt["database"],
        "private_values_exported": False,
    }


def _initial_state(directory):
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != 0:
        raise spec.ConfigurationError("DESKTOP_INIT_STATE_REQUIRED")
    if any(directory.iterdir()):
        if stat.S_IMODE(directory.stat().st_mode) != 0o700:
            raise spec.ConfigurationError("DESKTOP_INIT_STATE_CHANGED")
    else:
        directory.chmod(0o700)


def _profile(directory, raw):
    if directory.is_symlink() or not directory.is_dir():
        raise spec.ConfigurationError("DESKTOP_ROLE_VOLUME_REQUIRED")
    path = directory / "profile.json"
    if path.exists():
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != UID
            or stat.S_IMODE(info.st_mode) != 0o600
            or path.read_bytes() != raw
            or directory.stat().st_uid != UID
            or stat.S_IMODE(directory.stat().st_mode) != 0o700
        ):
            raise spec.ConfigurationError("DESKTOP_PROFILE_BINDING_CHANGED")
    else:
        if any(directory.iterdir()):
            raise spec.ConfigurationError("DESKTOP_PROFILE_PARTIAL_STATE")
        directory.chmod(0o700)
        os.chown(directory, UID, UID)
        spec.write_private(path, raw)
        os.chown(path, UID, UID)


def publish():
    value, _ = _binding()
    receipt = spec.load_private_json(PRIVATE / "runtime-receipt.json")
    if receipt["plan_digest"] != value["plan_digest"] or receipt["runtime_roles"] != sorted(
        desktop.ROLES
    ):
        raise spec.ConfigurationError("DESKTOP_RUNTIME_RECEIPT_CHANGED")
    for role in desktop.ROLES:
        raw = spec.private_file(PRIVATE / "runtime" / role / "profile.json")
        profile = json.loads(raw)
        spec.validate_role(profile)
        if profile["role"] != role or profile["plan_digest"] != value["plan_digest"]:
            raise spec.ConfigurationError("DESKTOP_ROLE_BINDING_CHANGED")
        _profile(Path("/profiles") / role, raw)
    state = Path("/api-state")
    if state.is_symlink() or not state.is_dir():
        raise spec.ConfigurationError("DESKTOP_API_STATE_REQUIRED")
    if any(state.iterdir()):
        if state.stat().st_uid != UID or stat.S_IMODE(state.stat().st_mode) != 0o700:
            raise spec.ConfigurationError("DESKTOP_API_STATE_CHANGED")
    else:
        state.chmod(0o700)
        os.chown(state, UID, UID)
    _profile(
        Path("/validation-login"),
        desktop.encoded(
            {
                "version": desktop.VERSION,
                "plan_digest": value["plan_digest"],
                "origin": value["plan"]["origin"],
                "login_name": "admin",
                "password": value["admin_password"],
            }
        ),
    )
    return {
        "stage": "published_role_profiles",
        "roles": list(desktop.ROLES),
        "private_values_exported": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("configure", "initialize", "publish"))
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        value = {"configure": configure, "initialize": initialize, "publish": publish}[args.stage]()
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, (spec.ConfigurationError, spec.fresh.BootstrapError))
            and re.fullmatch(r"[A-Z_]+", str(error))
            else "DESKTOP_PRIVATE_STAGE_FAILED"
        )
        details = {"failure_type": type(error).__name__}
        sqlstate = getattr(error, "sqlstate", None)
        if isinstance(sqlstate, str) and re.fullmatch(r"[A-Z0-9]{5}", sqlstate):
            details["sqlstate"] = sqlstate
        print(json.dumps({"ok": False, "code": code, **details}))
        return 2
    print(json.dumps({"ok": True, **value}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
