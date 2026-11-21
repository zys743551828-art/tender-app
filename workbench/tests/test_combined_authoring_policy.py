"""Opt-in composition: preserve even previously queued individual-mode identities."""

import pytest

from packages.authoring import (
    bound_format_scope,
    combined_authoring_scope,
    package_admission,
    package_generation,
    saved_chapter_plans,
)
from packages.authoring import plan_policy_compatibility as compatibility
from packages.authoring.combined_scope_policy_compatibility import V3_EQUIVALENTS
from packages.domain.runtime import ROOT, sha


@pytest.mark.parametrize(
    ("profile", "digest", "mixed_marker"),
    [
        (
            package_admission.profile,
            "9697a9ab32eb815d7d0ddfd50aa39aa137e5067dd768d0d1b080b34c2ca1ada9",
            combined_authoring_scope.INPUT_METHOD,
        ),
        (
            package_generation.policy,
            "4275f99b9a418dfd3e0f962d6e7e29d50cc659cef845e1f477e2d5c9aedcb0aa",
            combined_authoring_scope.EXECUTION_METHOD,
        ),
    ],
)
def test_combination_creates_its_own_method_and_preserves_exact_numeric_fingerprint(
    profile, digest, mixed_marker
):
    old = profile(bound_format=True)
    mixed = profile(saved_plans=True, bound_format=True)
    assert sha(old) == digest and sha(mixed) != digest
    assert "combined_scope_method" not in old
    assert mixed["combined_scope_method"] == mixed_marker
    assert mixed["bound_format_method"] == old["bound_format_method"]
    assert mixed["saved_plan_method"] == profile(saved_plans=True)["saved_plan_method"]
    assert combined_authoring_scope.DDL not in old["source_sha256"]
    assert set(old["source_sha256"]) < set(mixed["source_sha256"])
    assert all(
        digest == sha((ROOT / name).read_bytes()) for name, digest in mixed["source_sha256"].items()
    )


def test_unknown_current_source_is_not_mapped_to_the_v3_or_older_fingerprint(tmp_path, monkeypatch):
    candidates = {
        *V3_EQUIVALENTS,
        compatibility.COMPATIBILITY,
        bound_format_scope.HELPER,
        bound_format_scope.DDL,
        saved_chapter_plans.HELPER,
        saved_chapter_plans.DDL,
        "packages/authoring/bound_format_policy_compatibility.py",
        "packages/authoring/format_bindings.py",
        "packages/authoring/planning.py",
        "packages/domain/fact_sets.py",
        "packages/domain/human_decisions.py",
        "packages/domain/review_data.py",
    }
    unknown = b"unknown scope source - never certify as a tested identity"
    for name in candidates:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(unknown)
    monkeypatch.setattr(compatibility, "ROOT", tmp_path)
    for saved, numeric in [(False, False), (True, False), (False, True)]:
        got = compatibility.source_hashes(
            tuple(V3_EQUIVALENTS), saved_plans=saved, bound_format=numeric
        )
        assert all(got[name] == sha(unknown) for name in V3_EQUIVALENTS)
