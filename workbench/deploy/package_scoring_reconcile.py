"""Apply an owner-registered synthetic provider receipt without sending a request.

The receipt body is not accepted by this command. The independent SQL authority
requires a dedicated test reconciler and a separately registered disposable DB.
"""

import argparse
import json
import os
import shlex
import stat
import subprocess  # nosec B404
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def environment(profile):
    path = Path(profile)
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 16384
    ):
        raise ValueError("PACKAGE_SCORE_RECONCILIATION_PROFILE_MUST_BE_PRIVATE")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        if not separator or key.strip() != "PACKAGE_SCORE_RECONCILIATION_DSN" or values:
            raise ValueError("PACKAGE_SCORE_RECONCILIATION_PROFILE_MUST_HAVE_ONE_DSN")
        items = shlex.split(raw, comments=True)
        if len(items) != 1 or not items[0]:
            raise ValueError("PACKAGE_SCORE_RECONCILIATION_PROFILE_INVALID")
        values[key.strip()] = items[0]
    if not values:
        raise ValueError("PACKAGE_SCORE_RECONCILIATION_PROFILE_MISSING_DSN")
    return values | {
        "WORKBENCH_ENV_FILE": "/dev/null",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--receipt-id", type=UUID, required=True)
    parser.add_argument("--command-key", type=UUID, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--owned-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.owned_child:
        if args.profile is None:
            parser.error("--profile is required")
        # Fixed interpreter and owned script; argument bytes never pass a shell.
        result = subprocess.run(  # nosec B603
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--owned-child",
                "--receipt-id",
                str(args.receipt_id),
                "--command-key",
                str(args.command_key),
                "--reason",
                args.reason,
            ],
            cwd=ROOT,
            env=environment(args.profile),
            check=False,
        )
        return result.returncode
    if args.profile is not None or os.environ.get("WORKBENCH_ENV_FILE") != "/dev/null":
        raise ValueError("PACKAGE_SCORE_RECONCILIATION_CHILD_NOT_ISOLATED")
    sys.path.insert(0, str(ROOT))
    from packages.domain.runtime import DomainError
    from packages.model_governance.package_scoring_recovery import reconcile

    try:
        result = reconcile(args.receipt_id, args.command_key, args.reason)
    except DomainError as error:
        print(
            json.dumps({"ok": False, "code": error.code, "provider_requests": 0, "paid_calls": 0})
        )
        return 2
    print(json.dumps({"ok": True, "receipt": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
