"""Run reproducible CI suites and retain failures, errors and skipped coverage separately.

The PostgreSQL suite requires an explicitly disposable local cluster. It uses
the existing fixtures, which create temporary databases and non-owner logins;
the bootstrap connection is never substituted for an application identity.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PG_GROUPS = (
    "tender_api",
    "tender_worker",
    "tender_score_read",
    "tender_research_read",
    "tender_research_worker",
    "tender_assistant_budget_admin",
)


def junit_summary(path: Path) -> dict:
    # This is the local test runner's XML, not a user-supplied document.
    root = ElementTree.parse(path).getroot()  # nosec B314
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("CI_JUNIT_ROOT_INVALID")
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("CI_JUNIT_HAS_NO_TEST_CASES")
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = [item for case in cases if (item := case.find("skipped")) is not None]
    reasons = Counter(item.get("message") or item.text or "unspecified" for item in skipped)
    return {
        "tests": len(cases),
        "passed": len(cases) - failures - errors - len(skipped),
        "failures": failures,
        "errors": errors,
        "skipped": len(skipped),
        "skip_reasons": [
            {"reason": reason, "count": count} for reason, count in sorted(reasons.items())
        ],
    }


def test_environment() -> dict[str, str]:
    # Do not discover a business profile, service DSN or paid provider from the host.
    allowed = {
        "PATH",
        "LANG",
        "LC_ALL",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "PARSING_TEST_FONT_PATH",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed} | {
        "WORKBENCH_ENV_FILE": "explicit-ci-no-business-profile",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }


def postgres_environment(
    *, disposable: bool, initialize_groups: bool = True, require_tcp_password: bool = False
) -> dict[str, str]:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    if not disposable:
        raise ValueError("CI_POSTGRES_REQUIRES_EXPLICIT_DISPOSABLE_CLUSTER")
    dsn = os.environ.get("CI_POSTGRES_DSN")
    if not dsn:
        raise ValueError("CI_POSTGRES_DSN_REQUIRED")
    fields = conninfo_to_dict(dsn)
    if (
        {"hostaddr", "service"} & fields.keys()
        or any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE"))
        or not fields.get("user")
        or not fields.get("port")
    ):
        # libpq routing overrides must not bypass the explicit loopback check.
        raise ValueError("CI_POSTGRES_REQUIRES_EXPLICIT_LOCAL_POSTGRES_DATABASE")
    host = fields.get("host", "")
    if not isinstance(host, str):
        raise ValueError("CI_POSTGRES_REQUIRES_EXPLICIT_LOCAL_POSTGRES_DATABASE")
    local_socket = host.startswith("/") and Path(host).is_dir()
    if (host not in {"127.0.0.1", "localhost", "::1"} and not local_socket) or fields.get(
        "dbname"
    ) != "postgres":
        raise ValueError("CI_POSTGRES_REQUIRES_EXPLICIT_LOCAL_POSTGRES_DATABASE")
    if require_tcp_password and (host != "127.0.0.1" or not fields.get("password")):
        raise ValueError("CI_CANDIDATE_REQUIRES_EXPLICIT_LOOPBACK_PASSWORD_AUTH")
    if require_tcp_password:
        # Fresh bootstrap derives query-free identity URIs. Preserve that exact
        # identity: libpq options cannot be carried through or silently removed.
        if fields.keys() - {"host", "port", "user", "password", "dbname"}:
            raise ValueError("CI_CANDIDATE_REQUIRES_EXACT_CONNECTION_IDENTITY")
        dsn = make_conninfo(dsn)
    else:
        dsn = make_conninfo(dsn, options="-c jit=off")
    with psycopg.connect(dsn, autocommit=True) as connection:
        if connection.info.server_version // 10000 != 17:
            raise ValueError("CI_POSTGRES_17_REQUIRED")
        groups = PG_GROUPS if initialize_groups else ()
        for group in groups:
            row = connection.execute(
                "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                "FROM pg_roles WHERE rolname=%s",
                (group,),
            ).fetchone()
            if row is None:
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(group))
                )
            elif any(row):
                raise ValueError("CI_EXISTING_GROUP_PRIVILEGES_INVALID")
    return test_environment() | {"FUSION_REQUIREMENTS_ADMIN_DSN": dsn}


def suite_files(suite: str) -> list[str]:
    if suite == "unit":
        return ["tests"]
    if suite == "authoring":
        return [
            "tests/test_authoring_exact_revisions_pg.py",
            "tests/test_authoring_exact_builds_pg.py",
            "tests/test_authoring_exact_text_edits_pg.py",
        ]
    if suite == "scoring":
        return [
            "tests/test_material_request_preflight_pg.py",
            "tests/test_material_execution_attempts_pg.py",
        ]
    if suite == "candidate":
        return ["tests/test_authoring_candidate_pg.py"]
    if suite == "dispatch":
        return ["tests/test_material_execution_dispatch_pg.py"]
    # Reuse the existing suite definitions; no integration test is counted as
    # covered by the unit job just because its environment-gated test was skipped.
    from deploy.fusion_checks import SUITES

    return list(
        dict.fromkeys(
            name
            for group in (
                "requirements-api",
                "scope-review-api",
                "project-summaries",
                "package-next-actions",
            )
            for name in SUITES[group]
        )
    )


def write_summary(summary: dict, directory: Path, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    text = (
        f"## {label}\n\n"
        "| Passed | Failed | Errors | Skipped |\n| ---: | ---: | ---: | ---: |\n"
        f"| {summary['passed']} | {summary['failures']} | {summary['errors']} | {summary['skipped']} |\n\n"
        "Skipped tests are unverified coverage, not successful acceptance. "
        "See summary.json for the exact skip reasons.\n"
    )
    (directory / "summary.md").write_text(text, encoding="utf-8")
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as output:
            output.write(text)
    print(text, flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("unit", "postgres", "authoring", "scoring", "candidate", "dispatch"),
        required=True,
    )
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--disposable-postgres", action="store_true")
    parser.add_argument(
        "--weed", type=Path, help="Verified SeaweedFS binary; required for authoring"
    )
    parser.add_argument(
        "--kafka-home",
        type=Path,
        help="Verified Kafka 4.1.2 release directory; required for dispatch",
    )
    args = parser.parse_args(argv)
    if args.suite == "authoring" and args.weed is None:
        parser.error("authoring requires --weed pointing to the verified SeaweedFS binary")
    if args.suite == "dispatch" and args.kafka_home is None:
        parser.error("dispatch requires --kafka-home pointing to the verified Kafka 4.1.2 release")
    directory = (args.report_dir or ROOT / ".local" / "ci" / args.suite).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "junit.xml"
    # A crashed run must not leave previous successful evidence at this location.
    for name in ("junit.xml", "summary.json", "summary.md", "s3.log", "kafka.log"):
        (directory / name).unlink(missing_ok=True)
    environment = (
        test_environment()
        if args.suite == "unit"
        else postgres_environment(
            disposable=args.disposable_postgres,
            initialize_groups=args.suite != "candidate",
            require_tcp_password=args.suite == "candidate",
        )
    )
    if args.suite == "scoring":
        environment["FUSION_MATERIAL_REQUEST_PREFLIGHT_PG"] = "1"
        environment["FUSION_MATERIAL_EXECUTION_PG"] = "1"
    elif args.suite == "candidate":
        environment["FUSION_AUTHORING_CANDIDATE_ADMIN_DSN"] = environment.pop(
            "FUSION_REQUIREMENTS_ADMIN_DSN"
        )
        environment["FUSION_AUTHORING_CANDIDATE_PG"] = "1"
    with ExitStack() as services:
        if args.suite == "dispatch":
            from deploy.ci_kafka import temporary_kafka

            service_environment = test_environment()
            if java_home := os.environ.get("JAVA_HOME"):
                service_environment["JAVA_HOME"] = java_home
            environment["FUSION_MATERIAL_DISPATCH_PG"] = "1"
            environment.update(
                services.enter_context(
                    temporary_kafka(args.kafka_home, service_environment, directory / "kafka.log")
                )
            )
        if args.suite == "authoring":
            from deploy.ci_object_store import temporary_object_store

            environment["FUSION_AUTHORING_INPUT_ADMIN_DSN"] = environment.pop(
                "FUSION_REQUIREMENTS_ADMIN_DSN"
            )
            environment.update(
                services.enter_context(
                    temporary_object_store(args.weed, test_environment(), directory / "s3.log")
                )
            )
        result = subprocess.run(  # nosec B603
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-ra",
                "--tb=short",
                *suite_files(args.suite),
                "--junitxml=" + str(report),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
        )
    if not report.is_file():
        print("CI_JUNIT_NOT_PRODUCED", file=sys.stderr)
        return result.returncode or 1
    summary = junit_summary(report)
    summary["suite"] = args.suite
    summary["runner_exit_code"] = result.returncode
    write_summary(summary, directory, "Backend " + args.suite)
    if summary["errors"] or summary["failures"]:
        return result.returncode or 1
    if args.suite != "unit" and summary["skipped"]:
        print("CI_NATIVE_SKIPPED_COVERAGE_IS_NOT_ACCEPTED", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    # Invocation as `python deploy/ci_checks.py` must resolve sibling packages.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
