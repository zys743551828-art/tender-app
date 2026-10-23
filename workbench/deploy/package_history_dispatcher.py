"""Explicit bounded polling of already registered CPU jobs using one private purpose."""

import argparse
import json
import signal
import subprocess  # nosec B404
import sys
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purpose", choices=("train", "evaluate"), required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--owned-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (
        not 1 <= args.batch_size <= 20
        or not 1 <= args.cycles <= 1_000_000
        or not 1 <= args.poll_seconds <= 300
    ):
        parser.error("batch-size 1..20, cycles 1..1000000 and poll-seconds 1..300 required")
    if (args.profile is None) != args.owned_child:
        parser.error("parent requires a private profile; child must not receive it")
    return args


def main(argv=None):
    args = arguments(argv)
    sys.path.insert(0, str(ROOT))
    if not args.owned_child:
        from deploy.package_history_worker import environment

        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--owned-child",
            "--purpose",
            args.purpose,
            "--batch-size",
            str(args.batch_size),
            "--cycles",
            str(args.cycles),
            "--poll-seconds",
            str(args.poll_seconds),
        ]
        try:
            isolated = environment(args.profile, args.purpose)
        except (OSError, TypeError, ValueError):
            print(json.dumps({"ok": False, "code": "PACKAGE_HISTORY_DISPATCH_PROFILE_INVALID"}))
            return 2
        return subprocess.run(command, cwd=ROOT, env=isolated, check=False).returncode  # nosec B603

    import psycopg

    from packages.model_governance import package_history_dispatch as dispatch
    from packages.model_governance.common import GovernanceError

    stopped = Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda _signal, _frame: stopped.set())
    cursor = None
    try:
        for number in range(args.cycles):
            if stopped.is_set():
                break
            cursor, result = dispatch.cycle(
                args.purpose, after=cursor, limit=args.batch_size, stopped=stopped
            )
            print(json.dumps({"ok": True, "result": result}), flush=True)
            if number + 1 < args.cycles and stopped.wait(args.poll_seconds):
                break
    except (
        psycopg.Error,
        GovernanceError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        ArithmeticError,
    ):
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "PACKAGE_HISTORY_DISPATCH_UNAVAILABLE",
                    "provider_requests": 0,
                    "paid_calls": 0,
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
