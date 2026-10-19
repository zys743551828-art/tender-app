"""Whole-package method declaration; never borrows the single-body executor identity."""

import os

from packages.domain.review_identity import digest
from packages.domain.runtime import ROOT, sha

PURPOSE = "prebid_compliance"
POLICY = {
    "version": "package-prebid/1",
    "purpose": PURPOSE,
    "complete_package_required": True,
    "executor_available": False,
    "formal_scoring_eligible": False,
}


def profile():
    return {
        "engine": "package-review/1",
        "execution_status": "not_implemented",
        "purpose": PURPOSE,
        "configured_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
        "input_scope": "explicit_frozen_package_members",
        "source_digest": digest(
            {
                name: sha((ROOT / name).read_bytes())
                for name in (
                    "packages/domain/package_review_method.py",
                    "packages/domain/package_review_identity.py",
                    "packages/domain/package_review_frozen_input.py",
                    "packages/domain/package_review_eligibility.py",
                    "packages/domain/bid_package_review_eligibility.py",
                    "packages/domain/package_review_context.py",
                    "packages/domain/bid_package_original_verification.py",
                    "packages/domain/bid_package_review_freezing.py",
                    "packages/domain/bid_package_review_input_repository.py",
                    "packages/contracts/sql/bid-package-review-inputs.sql",
                    "packages/domain/original_verification.py",
                    "packages/domain/bid_package_review_repository.py",
                    "packages/domain/bid_package_repository.py",
                    "packages/domain/bid_package_review_documents.py",
                    "packages/domain/bid_package_review_policy.py",
                    "packages/domain/review_identity.py",
                    "packages/domain/providers/deepseek.py",
                )
            }
        ),
        "executor_available": False,
        "formal_scoring_eligible": False,
    }
