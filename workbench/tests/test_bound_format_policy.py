"""Numeric formatting is a third audited path, not a rename of old policy."""

from copy import deepcopy

import pytest

from packages.authoring import bound_format_scope, package_admission, package_generation
from packages.authoring import plan_policy_compatibility as compatibility
from packages.authoring.bound_format_policy_compatibility import V2_EQUIVALENTS
from packages.domain.runtime import ROOT, sha


@pytest.mark.parametrize(
    ("method", "legacy_digest", "saved_plan_digest", "new_marker"),
    [
        (
            package_admission.profile,
            "424f1854422cd3472582bfc2ba3b2f921262c3ad85cf82479f3d24deedc151be",
            "34bf10e27f062065298e622ae9ec824afb2c72352f33f1b1df7bf9729ceee3a4",
            bound_format_scope.INPUT_METHOD,
        ),
        (
            package_generation.policy,
            "0d72e7936033d5754d430105ef811400b2737cd3cc3842a136e8ac626b9d657c",
            "5b8406208f633692848aaaf5961c67b639e9d700d16eb72b9fa1767a899842ca",
            bound_format_scope.EXECUTION_METHOD,
        ),
    ],
)
def test_new_method_keeps_both_previous_exact_byte_identities(
    method, legacy_digest, saved_plan_digest, new_marker
):
    plain = method()
    planned = method(saved_plans=True)
    numeric = method(bound_format=True)
    assert sha(plain) == legacy_digest
    assert sha(planned) == saved_plan_digest
    assert numeric["bound_format_method"] == new_marker
    assert "bound_format_method" not in plain and "bound_format_method" not in planned
    assert "saved_plan_method" not in numeric
    assert sha(numeric) not in (legacy_digest, saved_plan_digest)
    for name, digest in numeric["source_sha256"].items():
        assert digest == sha((ROOT / name).read_bytes())
    for name, (previous, current) in V2_EQUIVALENTS.items():
        if name in numeric["source_sha256"]:
            assert numeric["source_sha256"][name] == current
            assert planned["source_sha256"][name] == previous
    with pytest.raises(ValueError):
        method(saved_plans=True, bound_format=True)


def test_vetted_aliases_never_certify_an_unknown_checked_file(tmp_path, monkeypatch):
    for path in {bound_format_scope.HELPER, bound_format_scope.DDL, *V2_EQUIVALENTS} | {
        "packages/authoring/saved_chapter_plans.py",
        "packages/contracts/sql/authoring-saved-plan-scope.sql",
        "packages/authoring/planning.py",
        "packages/authoring/format_bindings.py",
    }:
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"unreviewed implementation - never a previous policy")
    monkeypatch.setattr(compatibility, "ROOT", tmp_path)
    values = compatibility.source_hashes(tuple(V2_EQUIVALENTS), saved_plans=True)
    for filename, (old, known) in V2_EQUIVALENTS.items():
        assert old != known
        assert values[filename] not in (old, known)


def test_only_supported_numeric_fields_and_no_combined_metadata_pass_shape():
    bindings = [{"field": name, "value": 24} for name in bound_format_scope.FIELDS]
    snapshot = {"plans": {}, "metadata": {"format_bindings": bindings}}
    assert bound_format_scope.present(snapshot) and bound_format_scope.supported(snapshot)
    for broken in [
        {"plans": {"one": {"id": "one"}}},
        {"metadata": {"format_bindings": bindings, "word_import_sources": ["file"]}},
        {"metadata": {"format_bindings": [bindings[0], bindings[0]]}},
        {"metadata": {"format_bindings": [{"field": "page_number", "value": True}]}},
        {"metadata": {"format_bindings": [bindings[0] | {"value": False}]}},
        {"metadata": {"format_binding_manifest": [bindings[0]]}},
    ]:
        rejected = snapshot | broken
        assert bound_format_scope.present(rejected) and not bound_format_scope.supported(rejected)


def test_provider_projection_preserves_exact_content_and_does_not_mutate_bound_layout():
    ext = {"id": "fixed", "metadata": {"format_bindings": [{"reason": "Internal"}]}}
    target = {
        "snapshot_manifest": {"id": "same", "authoring_structure": deepcopy(ext)},
        "snapshot": {"id": "same", "authoring_structure": deepcopy(ext)},
        "sections": [{"existing": "frozen contents remain"}],
    }
    input_ = {"context": {"target": target, "documents": [{"role": "authority"}]}}
    original = deepcopy(input_)
    projected = bound_format_scope.model_projection(input_)
    assert input_ == original
    assert projected == {
        "context": {
            "target": {
                "snapshot_manifest": {"id": "same"},
                "snapshot": {"id": "same"},
                "sections": target["sections"],
            },
            "documents": [{"role": "authority"}],
        }
    }
