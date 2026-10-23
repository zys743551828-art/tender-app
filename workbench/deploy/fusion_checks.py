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
    "technical-scope-pure": [
        "tests/test_package_technical_scope.py",
        "tests/test_package_technical_eligibility.py",
        "tests/test_scale_authority.py",
    ],
    "technical-scope-api": [
        "tests/test_package_technical_scope_pg.py",
        "tests/test_package_technical_eligibility_pg.py",
        "tests/test_package_technical_eligibility_catalog_pg.py",
        "tests/test_package_technical_scale_pg.py",
    ],
    "requirements-api": [
        "tests/test_bid_package_requirements_api.py",
        "tests/test_bid_package_evidence_api.py",
        "tests/test_bid_package_review_preview_api.py",
        "tests/test_bid_package_original_verification_api.py",
        "tests/test_bid_package_review_freezing_api.py",
    ],
    "scope-review-pure": [
        "tests/test_package_scope_review.py",
        "tests/test_package_scope_review_identity.py",
        "tests/test_package_review_comparison.py",
        "tests/test_bid_package_review_comparisons.py",
        "tests/test_bid_package_scope_review.py",
        "tests/test_package_review_handlers.py",
        "tests/test_package_review_decisions.py",
        "tests/test_bid_package_review_decisions.py",
        "tests/test_dependency_capacity.py",
        "tests/test_evidence_status_projection.py",
        "tests/test_reconciliation_fairness.py",
        "tests/test_task_guard_entrypoints.py",
    ],
    "scope-review-api": [
        "tests/test_package_review_runs_api.py",
        "tests/test_package_review_decisions_api.py",
        "tests/test_package_scope_identity_facts_api.py",
        "tests/test_package_review_comparisons_api.py",
    ],
}
SUITES["completion-pure"] = [
    *SUITES["scope-review-pure"],
    "tests/test_package_review_reports.py",
    "tests/test_authoring_package_outputs.py",
    "tests/test_bid_package_generated_output_admission.py",
    "tests/test_document_parses.py",
    "tests/test_authoring_m1_composition.py",
]
SUITES["completion-api"] = [
    *SUITES["scope-review-api"],
    "tests/test_package_review_reports_api.py",
    "tests/test_authoring_package_adoptions_pg.py",
    "tests/test_package_generated_output_admission_pg.py",
    "tests/test_document_parses_pg.py",
]
SUITES["delivery-pure"] = [
    *SUITES["pure"],
    "tests/test_fusion_full_profile.py",
    "tests/test_package_history.py",
    "tests/test_package_history_directory.py",
    "tests/test_package_history_protocol_recovery.py",
]
SUITES["history-dispatch"] = [
    "tests/test_package_history_dispatch.py",
    "tests/test_package_history_dispatch_pg.py",
]
SUITES["desktop-pure"] = [
    *SUITES["delivery-pure"],
    "tests/test_fusion_desktop_compose.py",
    "tests/test_fusion_desktop_private.py",
]
SUITES["project-summaries"] = [
    "tests/test_project_summary.py",
    "tests/test_project_summary_api.py",
]
SUITES["package-next-actions"] = [
    "tests/test_package_next_actions.py",
    "tests/test_work_contexts.py",
    "tests/test_package_next_actions_api.py",
]
SUITES["technical-features-pure"] = [
    "tests/test_package_technical_features.py",
    "tests/test_scoring_contracts_profiles.py",
    "tests/test_package_scoring_recovery.py",
    "tests/test_fusion_compose.py",
]
SUITES["technical-assets-pure"] = [
    "tests/test_package_technical_assets.py",
    "tests/test_document_parses.py",
    "tests/test_fusion_compose.py",
]
SUITES["technical-input-pure"] = [
    "tests/test_package_technical_input.py",
    "tests/test_package_technical_assets.py",
    "tests/test_package_technical_features.py",
    "tests/test_fusion_compose.py",
]


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
    if suite in {"delivery-pure", "desktop-pure"}:
        shutil.copyfile("/workspace/requirements.lock.txt", root / "requirements.lock.txt")
        shutil.copytree("/workspace/apps/web/dist", root / "apps/web/dist")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "WORKBENCH_ENV_FILE": "explicit-fusion-checks-no-business-profile",
    }
    if suite == "technical-assets-pure":
        environment["FUSION_PAGE_ASSET_EVIDENCE"] = "1"
    if suite in {
        "budget",
        "requirements-api",
        "scope-review-api",
        "completion-api",
        "technical-scope-api",
        "history-dispatch",
        "project-summaries",
        "package-next-actions",
    }:
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
            if suite == "technical-scope-api":
                environment["FUSION_TECHNICAL_SCOPE_PG"] = "1"
            if suite == "history-dispatch":
                environment["FUSION_PACKAGE_HISTORY_DISPATCH_PG"] = "1"
                environment["FUSION_HISTORY_DISPATCH_EVIDENCE"] = "/evidence"
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
