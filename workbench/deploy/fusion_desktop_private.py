"""Linux Compose setup stages; private values remain in dedicated volumes."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

from botocore.exceptions import ClientError

from deploy import fusion_desktop_compose as desktop
from deploy import fusion_full_spec as spec

PRIVATE = Path(desktop.PRIVATE)
PUBLIC = Path("/public")
UID = 65532
MAX_BOOTSTRAP_BYTES = 16384


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
        or plan["model_configured"] != request.get("model_configured", False)
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


def _validate_bootstrap(value):
    if type(value) is not dict or set(value) != {"admin_password", "model"}:
        raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_INPUT_INVALID")
    password, model = value["admin_password"], value["model"]
    if password is not None and (
        type(password) is not str or len(password) < 8 or any(c in password for c in "\n\r\x00")
    ):
        raise spec.ConfigurationError("FULL_ADMIN_PASSWORD_REQUIRED")
    if model is not None:
        if type(model) is not dict:
            raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_INPUT_INVALID")
        spec.validate_model(model)
    return {"admin_password": password, "model": dict(model) if model is not None else None}


def read_bootstrap(stream):
    """Read bounded explicit bootstrap JSON; no secret is included in errors."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError()

    try:
        raw = stream.read(MAX_BOOTSTRAP_BYTES + 1)
        if type(raw) is str:
            raw = raw.encode("utf-8", errors="strict")
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BOOTSTRAP_BYTES:
            raise ValueError()
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant
        )
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_INPUT_INVALID") from None
    return _validate_bootstrap(value)


def configure(bootstrap=None):
    from deploy.fusion_full_configure import configure as create
    from deploy.fusion_full_dependencies import identity

    request = desktop.validate_request(json.loads((PUBLIC / "request.json").read_bytes()))
    supplied = _validate_bootstrap(bootstrap) if bootstrap is not None else None
    password = supplied["admin_password"] if supplied is not None else None
    model = supplied["model"] if supplied is not None else None
    if model is not None and not request.get("model_configured", False):
        raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_MODEL_INTENT_MISMATCH")
    identity()
    parent = PRIVATE.parent
    if parent.is_symlink() or not parent.is_dir():
        raise spec.ConfigurationError("DESKTOP_PRIVATE_VOLUME_REQUIRED")
    parent.chmod(0o700)
    if PRIVATE.exists():
        value, binding = _binding()
        if binding["request"] != request:
            raise spec.ConfigurationError("DESKTOP_REQUEST_CHANGED")
        if (password is not None and password != value["admin_password"]) or (
            model is not None and model != value["model"]
        ):
            raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_BINDING_CHANGED")
    else:
        if request.get("model_configured", False) and model is None:
            raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_MODEL_REQUIRED")
        create(
            PRIVATE,
            name=request["name"],
            origin=request["origin"],
            python_image=request["python_image"],
            web_image=request["web_image"],
            admin_password=password if password is not None else secrets.token_urlsafe(32),
            **({"model": model} if model is not None else {}),
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
    value, binding = _binding()
    receipt = spec.load_private_json(PRIVATE / "runtime-receipt.json")
    roles = desktop.roles(binding["request"])
    if receipt["plan_digest"] != value["plan_digest"] or receipt["runtime_roles"] != sorted(roles):
        raise spec.ConfigurationError("DESKTOP_RUNTIME_RECEIPT_CHANGED")
    for role in roles:
        raw = spec.private_file(PRIVATE / "runtime" / role / "profile.json")
        profile = json.loads(raw)
        spec.validate_role(profile)
        if profile["role"] != role or profile["plan_digest"] != value["plan_digest"]:
            raise spec.ConfigurationError("DESKTOP_ROLE_BINDING_CHANGED")
        _profile(Path("/profiles") / role, raw)
    if binding["request"]["version"] == desktop.WORD_VERSION:
        from deploy import fusion_word_spec as word

        for role, lanes in word.ROLE_LANES.items():
            target = Path("/profiles") / role
            profile = spec.load_private_json(PRIVATE / "runtime" / role / "profile.json")
            files = {
                "word-profile.json": word.installation(binding["request"], profile, role),
                **{
                    word.PROFILE_FILES[lane]: binding["request"]["word"]["profiles"][lane]
                    for lane in lanes
                },
            }
            for filename, document in files.items():
                path = target / filename
                encoded = desktop.encoded(document)
                if path.exists() or path.is_symlink():
                    info = path.lstat()
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_uid != UID
                        or info.st_gid != UID
                        or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) != 0o600
                        or path.read_bytes() != encoded
                    ):
                        raise spec.ConfigurationError("DESKTOP_WORD_PROFILE_BINDING_CHANGED")
                else:
                    spec.write_private(path, encoded)
                    os.chown(path, UID, UID)
    _application_state(Path("/api-state"))
    _profile(
        Path("/validation-login"),
        desktop.encoded(
            {
                "version": binding["request"]["version"],
                "plan_digest": value["plan_digest"],
                "origin": value["plan"]["origin"],
                "login_name": "admin",
                "password": value["admin_password"],
            }
        ),
    )
    return {
        "stage": "published_role_profiles",
        "roles": list(roles),
        "private_values_exported": False,
    }


def _application_state(state):
    if state.is_symlink() or not state.is_dir():
        raise spec.ConfigurationError("DESKTOP_API_STATE_REQUIRED")
    info = state.stat()
    if info.st_uid == UID and info.st_gid == UID and stat.S_IMODE(info.st_mode) == 0o700:
        return
    if info.st_uid != 0 or any(state.iterdir()):
        raise spec.ConfigurationError("DESKTOP_API_STATE_CHANGED")
    # Only a new root-owned empty volume is initialized. A repeated publisher
    # has CHOWN/DAC_OVERRIDE, not FOWNER, and must not chmod an application-owned dir.
    state.chmod(0o700)
    os.chown(state, UID, UID)


def _failure_details(error):
    details: dict[str, object] = {"failure_type": type(error).__name__}
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and re.fullmatch(r"[A-Z0-9]{5}", sqlstate):
        details["sqlstate"] = sqlstate
    if isinstance(error, ClientError):
        response = error.response if isinstance(error.response, dict) else {}
        information = response.get("Error")
        code = information.get("Code") if isinstance(information, dict) else None
        known = {
            "NoSuchKey",
            "NoSuchBucket",
            "BucketAlreadyExists",
            "BucketAlreadyOwnedByYou",
            "AccessDenied",
            "InvalidAccessKeyId",
            "SignatureDoesNotMatch",
            "RequestTimeout",
            "SlowDown",
            "ServiceUnavailable",
            "InternalError",
            "NotImplemented",
            "404",
            "403",
        }
        details["store_code"] = code if isinstance(code, str) and code in known else "UNCLASSIFIED"
        metadata = response.get("ResponseMetadata")
        status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
        if type(status) is int and 100 <= status <= 599:
            details["store_http_status"] = status
        if error.operation_name in {
            "GetObject",
            "HeadBucket",
            "CreateBucket",
            "ListBuckets",
            "PutObject",
        }:
            details["store_operation"] = error.operation_name
    return details


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("configure", "initialize", "publish"))
    parser.add_argument("--bootstrap-stdin", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.bootstrap_stdin and args.stage != "configure":
            raise spec.ConfigurationError("DESKTOP_BOOTSTRAP_STAGE_INVALID")
        if args.stage == "configure":
            value = (
                configure(read_bootstrap(sys.stdin.buffer)) if args.bootstrap_stdin else configure()
            )
        elif args.stage == "initialize":
            value = initialize()
        else:
            value = publish()
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, (spec.ConfigurationError, spec.fresh.BootstrapError))
            and re.fullmatch(r"[A-Z_]+", str(error))
            else "DESKTOP_PRIVATE_STAGE_FAILED"
        )
        print(json.dumps({"ok": False, "code": code, **_failure_details(error)}))
        return 2
    print(json.dumps({"ok": True, **value}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
