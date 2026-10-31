"""Execute one fixed application component with a positive allowlist of private values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.client import HTTPConnection, HTTPException
from pathlib import Path

from deploy import fusion_full_probe as probe
from deploy import fusion_full_spec as spec
from deploy.fusion_parsing_spec import environment as parsing_environment

MODEL_COMPONENTS = {"review", "assistant", "review-controller", "assistant-controller"}


def http_ready():
    # Fixed in-container loopback only; do not use inherited proxies or caller URLs.
    connection = HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request("GET", "/health/ready")
        response = connection.getresponse()
        raw = response.read(65537)
        value = json.loads(raw)
        if (
            len(raw) > 65536
            or response.status != 200
            or not isinstance(value, dict)
            or set(value) != {"database", "model", "slice"}
            or value["database"] != "ready"
            or value["model"] not in {"configured", "not_configured"}
            or value["slice"] != "pdf-and-core-review"
        ):
            raise ValueError
    except (HTTPException, OSError, ValueError):
        raise spec.ConfigurationError("FULL_API_HTTP_NOT_READY") from None
    finally:
        connection.close()
    return {"listener_verified": True, "authenticated_endpoint": False}


def environment(profile, component):
    if component not in spec.COMMANDS:
        raise spec.ConfigurationError("FULL_COMPONENT_UNKNOWN")
    spec.validate_role(profile)
    role, _ = spec.COMMANDS[component]
    if profile["role"] != role:
        raise spec.ConfigurationError("FULL_COMPONENT_ROLE_MISMATCH")
    if component in MODEL_COMPONENTS and not profile["plan"]["model_configured"]:
        raise spec.ConfigurationError("FULL_MODEL_PROFILE_REQUIRED")
    if component == "task-runner" and not profile["plan"]["task_runner_enabled"]:
        raise spec.ConfigurationError("FULL_TASK_RUNNER_DISABLED")
    # No inherited owner, alternative DSN, paid/test switch, proxy, user site or .env.
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(spec.fresh.ROOT),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "WORKBENCH_ENV_FILE": "explicit-fusion-full-runtime",
        "WORKBENCH_RUNTIME_ROLE": "worker"
        if "WORKER_DATABASE_DSN" in profile["environment"]
        else "api",
        **profile["environment"],
        **parsing_environment(profile["plan"], component),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=sorted(spec.COMMANDS))
    parser.add_argument("--profile", type=Path, default=Path("/runtime/profile.json"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify current dependencies; no consumer or model call",
    )
    args = parser.parse_args()
    try:
        profile = spec.load_private_json(args.profile)
        allowed = environment(profile, args.component)
        result = probe.check(profile)
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, spec.ConfigurationError)
            else "FULL_RUNTIME_STARTUP_FAILED_PRIVATE_DETAILS_SUPPRESSED"
        )
        raise SystemExit(code) from None
    if args.check:
        if args.component == "api":
            try:
                result["http"] = http_ready()
            except spec.ConfigurationError as error:
                raise SystemExit(str(error)) from None
        print(json.dumps(result, ensure_ascii=False))
        return
    print(
        json.dumps(
            {
                "component": args.component,
                "plan_digest": profile["plan_digest"],
                "database_role": result["database"]["role"],
                "state": "starting_verified_component",
            }
        ),
        flush=True,
    )
    _, command = spec.COMMANDS[args.component]
    os.execve(sys.executable, [sys.executable, "-m", *command], allowed)  # nosec B606


if __name__ == "__main__":
    main()
