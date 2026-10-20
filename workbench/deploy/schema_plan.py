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
    "packages/contracts/sql/roles.sql",
    "deploy/sql/bid-package-runtime-grants.sql",
    "deploy/sql/bid-package-requirement-runtime-grants.sql",
    "deploy/sql/bid-package-review-input-runtime-grants.sql",
    "deploy/sql/bid-package-execution-input-runtime-grants.sql",
    "deploy/sql/bid-package-fact-scope-runtime-grants.sql",
    "deploy/sql/vector-runtime-grants.sql",
    "deploy/sql/research-source-qualification.sql",
)
