"""Compose checks use fixed Python/suite arguments without a shell or disposable containers."""

import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

SUITES = {
    "pure": [
        "tests/test_initialize_database.py",
        "tests/test_bootstrap_fresh.py",
        "tests/test_external_profile.py",
        "tests/test_fusion_compose.py",
    ],
    "budget": ["tests/test_assistant_budget_nonowner.py"],
    "requirements-pure": ["tests/test_bid_package_requirements.py"],
    "requirements-api": [
        "tests/test_bid_package_requirements_api.py",
        "tests/test_bid_package_evidence_api.py",
        "tests/test_bid_package_review_preview_api.py",
    ],
}


def main():
    suite = os.environ.get("FUSION_CHECK_SUITE", "pure")
    if suite not in SUITES:
        raise SystemExit("FUSION_CHECK_SUITE_INVALID")
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="fusion-checks-"))
    root.chmod(0o700)
    ignore = shutil.ignore_patterns(
        ".env",
        ".env.*",
        ".local",
        "__pycache__",
        "node_modules",
        ".venv",
        "private",
        "secrets",
        "dist",
    )
    for name in ("packages", "deploy", "tests", "apps/api", "apps/worker"):
        shutil.copytree(Path("/workspace") / name, root / name, ignore=ignore)
    shutil.copyfile("/workspace/pyproject.toml", root / "pyproject.toml")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "WORKBENCH_ENV_FILE": "explicit-fusion-checks-no-business-profile",
    }
    if suite in {"budget", "requirements-api"}:
        password = (
            Path("/run/secrets/fusion_checks_owner_password")
            .read_text(encoding="utf-8")
            .rstrip("\r\n")
        )
        if not password:
            raise RuntimeError("FUSION_CHECK_PASSWORD_REQUIRED")
        check_dsn = f"postgresql://postgres:{quote(password, safe='')}@fusion-nonowner-postgres:5432/postgres"
        with psycopg.connect(check_dsn, autocommit=True) as c:
            for group in (
                "tender_api",
                "tender_worker",
                "tender_score_read",
                "tender_research_read",
                "tender_research_worker",
                "tender_assistant_budget_admin",
            ):
                if (
                    c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (group,)).fetchone()
                    is None
                ):
                    c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
        if suite == "budget":
            environment["FUSION_NONOWNER_OWNER_DSN"] = check_dsn
            environment["FUSION_NONOWNER_RECEIPT"] = "/evidence/budget-receipt.jsonl"
        else:
            environment["FUSION_REQUIREMENTS_ADMIN_DSN"] = check_dsn
    # The executable and suite paths are trusted constants; shell remains disabled.
    result = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "pytest",
            *SUITES[suite],
            "-q",
            "-x",
            "-p",
            "no:cacheprovider",
            f"--junitxml=/evidence/{suite}.xml",
        ],
        cwd=root,
        env=environment,
        check=False,
    )
    print(
        json.dumps(
            {
                "suite": suite,
                "exit_code": result.returncode,
                "real_provider_attempts": 0,
                "compose_project": "tender-fusion",
            }
        ),
        flush=True,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
