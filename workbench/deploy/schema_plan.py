"""Reviewed base schema order shared by fresh bootstrap and the empty-DB initializer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Add reviewed base inputs here once, in dependency order. Optional extensions stay opt-in.
BASE_SQL = (
    "packages/contracts/sql/core.sql",
    "packages/contracts/sql/domain.sql",
    "packages/contracts/sql/bid-packages.sql",
    "packages/identity/sql/stable-lot-identity.sql",
    "packages/contracts/sql/retrieval.sql",
    "packages/contracts/sql/worker-functions.sql",
    "packages/contracts/sql/bid-package-requirements.sql",
    "packages/contracts/sql/bid-package-review-inputs.sql",
    "packages/contracts/sql/bid-package-execution-inputs.sql",
    "packages/contracts/sql/bid-package-fact-scopes.sql",
    "packages/contracts/sql/bid-package-dependency-plans.sql",
    "packages/contracts/sql/bid-package-review-runs.sql",
    "packages/contracts/sql/bid-package-review-decisions.sql",
    "packages/contracts/sql/bid-package-report-exports.sql",
    "packages/contracts/sql/document-parses.sql",
    "packages/contracts/sql/roles.sql",
    "packages/authoring/sql/structure.sql",
    "packages/authoring/sql/rich_assets.sql",
    "packages/authoring/sql/docx_import.sql",
    "deploy/sql/bid-package-runtime-grants.sql",
    "deploy/sql/bid-package-requirement-runtime-grants.sql",
    "deploy/sql/bid-package-review-input-runtime-grants.sql",
    "deploy/sql/bid-package-execution-input-runtime-grants.sql",
    "deploy/sql/bid-package-fact-scope-runtime-grants.sql",
    "deploy/sql/bid-package-dependency-plan-runtime-grants.sql",
    "deploy/sql/bid-package-review-run-runtime-grants.sql",
    "packages/contracts/sql/bid-package-rule-corrections.sql",
    "deploy/sql/bid-package-review-decision-runtime-grants.sql",
    "deploy/sql/bid-package-report-runtime-grants.sql",
    "deploy/sql/document-parse-runtime-grants.sql",
    "deploy/sql/vector-runtime-grants.sql",
    "deploy/sql/research-source-qualification.sql",
    "packages/contracts/sql/bid-package-submissions.sql",
    "packages/contracts/sql/bid-package-technical-scopes.sql",
    "packages/contracts/sql/task-package-reviews.sql",
)
