"""Launch the dedicated material Kafka relay or production-admission worker.

The worker intentionally has no model credentials, synthetic fixture switch or
reader DSNs. Its current production result is a durable qualification blocker.
The isolated synthetic runtime is exercised separately by native acceptance.
"""

import argparse
import json
import os
import shlex
import stat

# The child is a fixed interpreter and owned script, without a shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = frozenset({"MATERIAL_DISPATCH_DSN", "MATERIAL_DISPATCH_KAFKA_BOOTSTRAP"})
RELAY = frozenset({"MATERIAL_DISPATCH_PROFILE_ID", "MATERIAL_DISPATCH_PROFILE_DIGEST"})


def environment(profile, purpose):
    if purpose not in {"relay", "worker"}:
        raise ValueError("MATERIAL_DISPATCH_PURPOSE_INVALID")
    path = Path(profile)
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 16384
    ):
        raise ValueError("MATERIAL_DISPATCH_PROFILE_MUST_BE_PRIVATE_REGULAR_FILE")
    expected = COMMON | (RELAY if purpose == "relay" else frozenset())
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        key = key.strip()
        if not separator or key not in expected or key in values:
            raise ValueError("MATERIAL_DISPATCH_PROFILE_KEYS_INVALID")
        try:
            items = shlex.split(raw, comments=True)
        except ValueError:
            raise ValueError("MATERIAL_DISPATCH_PROFILE_INVALID") from None
        if len(items) != 1 or not items[0]:
            raise ValueError("MATERIAL_DISPATCH_PROFILE_INVALID")
        values[key] = items[0]
    if set(values) != expected:
        raise ValueError("MATERIAL_DISPATCH_PROFILE_KEYS_INVALID")
    return values | {
        "WORKBENCH_ENV_FILE": "/dev/null",
        "MATERIAL_DISPATCH_OWNED_PURPOSE": purpose,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }


def _run(args):
    sys.path.insert(0, str(ROOT))
    import psycopg
    from psycopg.rows import dict_row

    from packages.model_governance import material_execution_dispatch as dispatch
    from packages.model_governance import material_execution_runtime as runtime

    if (
        args.profile is not None
        or os.environ.get("WORKBENCH_ENV_FILE") != "/dev/null"
        or os.environ.get("MATERIAL_DISPATCH_OWNED_PURPOSE") != args.purpose
    ):
        dispatch.fail("CHILD_NOT_ISOLATED")
    broker = None
    try:
        with psycopg.connect(
            os.environ["MATERIAL_DISPATCH_DSN"], autocommit=True, row_factory=dict_row
        ) as connection:
            method = dispatch.method_digest()
            if args.purpose == "relay":
                broker = runtime.producer(os.environ["MATERIAL_DISPATCH_KAFKA_BOOTSTRAP"])
            else:
                broker = runtime.consumer(os.environ["MATERIAL_DISPATCH_KAFKA_BOOTSTRAP"])
                broker.subscribe([runtime.TOPIC])
            while True:
                if args.purpose == "relay":
                    observed = runtime.relay_once(
                        connection,
                        broker,
                        profile_id=os.environ["MATERIAL_DISPATCH_PROFILE_ID"],
                        expected_profile_digest=os.environ["MATERIAL_DISPATCH_PROFILE_DIGEST"],
                        expected_method_digest=method,
                    )
                else:
                    consumed = runtime.consume_once(
                        connection, broker, expected_method_digest=method, timeout=5
                    )
                    observed = consumed.observation if consumed is not None else None
                if observed is not None:
                    doc = observed.metadata["lease"]["document"]
                    print(
                        json.dumps(
                            {
                                "event_id": doc["event_id"],
                                "job_id": doc["job_id"],
                                "state": observed.metadata["state"],
                                "production_send_authorized": False,
                            }
                        ),
                        flush=True,
                    )
                if args.once:
                    return 0
                if observed is None:
                    time.sleep(0.25)
    except dispatch.MaterialDispatchError as error:
        print(json.dumps({"ok": False, "code": str(error)}), flush=True)
        return 2
    except Exception:
        print(
            json.dumps({"ok": False, "code": "MATERIAL_DISPATCH_STARTUP_UNAVAILABLE"}), flush=True
        )
        return 2
    finally:
        if broker is not None and args.purpose == "worker":
            broker.close()


def main(*, injected_host=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--qualified-config", type=Path)
    parser.add_argument("--purpose", choices=("relay", "worker"), required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--owned-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.qualified_config is not None:
        # No CLI-controlled imports, credential environment variables or fallback.
        # A trusted embedding host supplies callbacks explicitly to main().
        try:
            if (
                injected_host is None
                or args.purpose != "worker"
                or args.profile is not None
                or args.owned_child
            ):
                raise ValueError("QUALIFIED_WORKER_DISABLED")
            path = args.qualified_config
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16384:
                raise ValueError("CONFIGURATION_INVALID")
            sys.path.insert(0, str(ROOT))
            from packages.model_governance import material_worker_host

            config = material_worker_host.read_config(path)
            if args.once and config.get("max_messages") != 1:
                raise ValueError("ONCE_REQUIRES_ONE_MESSAGE")
            report = material_worker_host.run(config, injected_host)
        except Exception:
            report = {"ok": False, "code": "QUALIFIED_WORKER_UNAVAILABLE"}
        print(json.dumps(report), flush=True)
        return 0 if report["ok"] else 2
    if args.owned_child:
        return _run(args)
    if args.profile is None:
        parser.error("--profile is required")
    try:
        env = environment(args.profile, args.purpose)
    except (OSError, ValueError):
        print(json.dumps({"ok": False, "code": "MATERIAL_DISPATCH_PRIVATE_PROFILE_INVALID"}))
        return 2
    command = [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--owned-child",
        "--purpose",
        args.purpose,
    ]
    if args.once:
        command.append("--once")
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode  # nosec B603


if __name__ == "__main__":
    raise SystemExit(main())
