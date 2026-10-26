"""One explicit native material job command, without Kafka, readers or model ports."""

import argparse
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = {"WORKBENCH_ENV_FILE": "/dev/null", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


def environment(profile):
    from packages.model_governance import package_feature_handoff as files

    data = files.decode(files.private_read(profile, maximum=16384))
    if (
        type(data) is not dict
        or set(data) != {"MATERIAL_JOB_DSN"}
        or type(data["MATERIAL_JOB_DSN"]) is not str
        or not data["MATERIAL_JOB_DSN"]
    ):
        raise ValueError("private profile required")
    return BASE | data


def child(args):
    import psycopg
    from psycopg.rows import dict_row

    from packages.model_governance import material_job_commands as commands
    from packages.model_governance import material_judgment_jobs as jobs

    try:
        if (
            set(os.environ) - (set(BASE) | {"LC_CTYPE", "MATERIAL_JOB_DSN"})
            or any(os.environ.get(k) != v for k, v in BASE.items())
            or args.profile
        ):
            raise ValueError("child isolation required")
        if args.action == "method":
            print(
                json.dumps(
                    {
                        "version": commands.VERSION,
                        "method_digest": jobs.method_digest(),
                        "execution_authorized": False,
                    }
                )
            )
            return 0
        command = commands.load(args.request, args.expected_request_digest)
        with psycopg.connect(
            os.environ["MATERIAL_JOB_DSN"], autocommit=True, row_factory=dict_row
        ) as connection:
            receipt = commands.execute(connection, command)
        print(json.dumps(receipt))
        return 0
    except jobs.JudgmentJobError as error:
        code = str(error)
        if code not in jobs.KNOWN_ERRORS | {
            "JUDGMENT_JOB_METHOD_MISMATCH",
            "JUDGMENT_JOB_NATIVE_METHOD_MISMATCH",
            "JUDGMENT_JOB_COMMAND_FILE_CHANGED",
        }:
            code = "MATERIAL_JOB_COMMAND_REJECTED"
    except Exception:
        # A transport/ACK error can follow a commit. No rollback or no-job claim.
        code = "MATERIAL_JOB_COMMAND_UNCONFIRMED"
    print(json.dumps({"ok": False, "code": code, "retry": "repeat_exact_original_command_or_read"}))
    return 2


def main():
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("method", "submit"), required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--expected-request-digest")
    parser.add_argument("--owned-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == "method" and any((args.profile, args.request, args.expected_request_digest)):
        parser.error("method accepts no configuration")
    if args.action == "submit" and (not args.request or not args.expected_request_digest):
        parser.error("submit requires a fixed request and digest")
    if args.owned_child:
        return child(args)
    if args.action == "submit" and not args.profile:
        parser.error("submit requires a private profile")
    try:
        env = environment(args.profile) if args.action == "submit" else dict(BASE)
    except Exception:
        print(json.dumps({"ok": False, "code": "MATERIAL_JOB_PRIVATE_PROFILE_INVALID"}))
        return 2
    command = [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--owned-child",
        "--action",
        args.action,
    ]
    if args.request:
        command += [
            "--request",
            str(args.request.absolute()),
            "--expected-request-digest",
            args.expected_request_digest,
        ]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode  # nosec B603


if __name__ == "__main__":
    raise SystemExit(main())
