"""Run one isolated evidence-verification or CPU-research purpose with a private profile."""

import argparse
import json
import shlex
import stat
import subprocess  # nosec B404
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
VARIABLES = {
    "verify": "PACKAGE_HISTORY_VERIFY_DSN",
    "train": "PACKAGE_HISTORY_TRAIN_DSN",
    "evaluate": "PACKAGE_HISTORY_EVALUATE_DSN",
}


def environment(profile, purpose):
    if purpose not in VARIABLES:
        raise ValueError("PACKAGE_HISTORY_PURPOSE_INVALID")
    path = Path(profile)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > 16384
    ):
        raise ValueError("PACKAGE_HISTORY_PROFILE_MUST_BE_PRIVATE")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, delimiter, raw = line.partition("=")
        if not delimiter or key.strip() != VARIABLES[purpose] or values:
            raise ValueError("PACKAGE_HISTORY_PROFILE_MUST_HAVE_ONE_PURPOSE_DSN")
        parts = shlex.split(raw, comments=True)
        if len(parts) != 1 or not parts[0]:
            raise ValueError("PACKAGE_HISTORY_PROFILE_INVALID")
        values[key.strip()] = parts[0]
    if not values:
        raise ValueError("PACKAGE_HISTORY_PROFILE_NOT_CONFIGURED")
    return values | {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purpose",
        choices=tuple(VARIABLES) + ("feature-method", "feature-freeze", "feature-read"),
        required=True,
    )
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--scope-id", type=UUID)
    parser.add_argument("--submission-id", type=UUID)
    parser.add_argument("--outcome-id", type=UUID)
    parser.add_argument("--adapter-id", type=UUID)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--job-id", type=UUID)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--owned-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--command-id", type=UUID)
    parser.add_argument("--projection", type=Path)
    parser.add_argument("--origin", choices=("synthetic_mechanism", "unqualified_research"))
    parser.add_argument("--expected-projection-digest")
    parser.add_argument("--expected-binding-digest")
    parser.add_argument("--expected-feature-method-digest")
    parser.add_argument("--expected-handoff-method-digest")
    parser.add_argument("--expected-artifact-digest")
    args = parser.parse_args()
    evidence = (args.scope_id, args.submission_id, args.outcome_id, args.adapter_id, args.evidence)
    feature_arguments = (
        args.artifact_dir,
        args.command_id,
        args.projection,
        args.origin,
        args.expected_projection_digest,
        args.expected_binding_digest,
        args.expected_feature_method_digest,
        args.expected_handoff_method_digest,
        args.expected_artifact_digest,
    )
    if args.purpose.startswith("feature-"):
        if (
            any(evidence)
            or args.profile is not None
            or args.job_id is not None
            or args.generation != 1
        ):
            parser.error("feature handoff cannot accept credentials, native evidence or a CPU job")
        if args.purpose == "feature-method":
            if any(value is not None for value in feature_arguments):
                parser.error("feature-method accepts no material or artifact")
        elif not all(
            (
                args.artifact_dir,
                args.command_id,
                args.origin,
                args.expected_projection_digest,
                args.expected_binding_digest,
                args.expected_feature_method_digest,
                args.expected_handoff_method_digest,
            )
        ):
            parser.error(
                "feature handoff requires exact command, origin and independent expected identities"
            )
        elif args.purpose == "feature-freeze" and (
            args.projection is None or args.expected_artifact_digest is not None
        ):
            parser.error("feature-freeze requires only a private source projection")
        elif args.purpose == "feature-read" and (
            args.projection is not None or args.expected_artifact_digest is None
        ):
            parser.error("feature-read requires the independently retained artifact digest")
        return parser, args
    if any(value is not None for value in feature_arguments):
        parser.error("native history purposes do not accept feature artifacts")
    if args.purpose == "verify":
        if not all(evidence) or args.job_id is not None:
            parser.error(
                "verification requires exact scope/submission/outcome/adapter and original evidence file"
            )
    elif any(evidence) or args.job_id is None or args.generation < 1:
        parser.error("CPU research requires only job ID and positive generation")
    return parser, args


def main():
    parser, args = arguments()
    if args.purpose.startswith("feature-"):
        sys.path.insert(0, str(ROOT))
        from deploy.package_feature_handoff import run

        return run(args)
    if not args.owned_child:
        if args.profile is None:
            parser.error("--profile is required")
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--owned-child",
            "--purpose",
            args.purpose,
        ]
        if args.purpose == "verify":
            command += [
                "--scope-id",
                str(args.scope_id),
                "--submission-id",
                str(args.submission_id),
                "--outcome-id",
                str(args.outcome_id),
                "--adapter-id",
                str(args.adapter_id),
                "--evidence",
                str(args.evidence.resolve()),
            ]
        else:
            command += ["--job-id", str(args.job_id), "--generation", str(args.generation)]
        return subprocess.run(
            command, cwd=ROOT, env=environment(args.profile, args.purpose), check=False
        ).returncode  # nosec B603
    if args.profile is not None:
        raise ValueError("PACKAGE_HISTORY_CHILD_NOT_ISOLATED")
    sys.path.insert(0, str(ROOT))
    import psycopg

    from packages.model_governance import package_history_runtime as runtime
    from packages.model_governance.common import GovernanceError

    try:
        if args.purpose == "verify":
            from packages.model_governance import package_history_proofs as proofs

            info = args.evidence.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > 2 * proofs.MAX_BYTES
            ):
                raise GovernanceError(
                    "PACKAGE_HISTORY_EVIDENCE_MUST_BE_PRIVATE",
                    "Private bounded evidence file required",
                )
            envelope = proofs.load(args.evidence.read_bytes())
            value = runtime.ingest(
                scope_id=args.scope_id,
                submission_id=args.submission_id,
                outcome_id=args.outcome_id,
                adapter_id=args.adapter_id,
                envelope=envelope,
            )
        else:
            value = runtime.run(args.purpose, args.job_id, args.generation)
    except GovernanceError as error:
        print(
            json.dumps({"ok": False, "code": error.code, "provider_requests": 0, "paid_calls": 0})
        )
        return 2
    except psycopg.Error as error:
        code = error.diag.message_primary or "PACKAGE_HISTORY_DATABASE_ERROR"
        if not code.startswith("package_history_"):
            code = "PACKAGE_HISTORY_DATABASE_ERROR"
        print(
            json.dumps({"ok": False, "code": code.upper(), "provider_requests": 0, "paid_calls": 0})
        )
        return 2
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError):
        # Fail the owned task without putting private source bytes, profile
        # contents or values from a malformed export into a traceback/log.
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "PACKAGE_HISTORY_EXECUTION_INVALID",
                    "provider_requests": 0,
                    "paid_calls": 0,
                }
            )
        )
        return 2
    print(json.dumps({"ok": True, "result": value}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
