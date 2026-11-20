"""Saved-plan profile separation and private model projection, without IO or a model."""

from copy import deepcopy

from packages.authoring import package_admission, package_generation, saved_chapter_plans
from packages.authoring import plan_policy_compatibility as compatibility
from packages.authoring.bound_format_policy_compatibility import V2_EQUIVALENTS
from packages.authoring.combined_scope_policy_compatibility import V3_EQUIVALENTS
from packages.domain.runtime import ROOT, sha


def test_known_no_plan_profile_uses_only_tested_equivalences():
    values = [
        (package_admission.profile, saved_chapter_plans.INPUT_METHOD),
        (package_generation.policy, saved_chapter_plans.EXECUTION_METHOD),
    ]
    seen = set()
    for profile, marker in values:
        old, planned = profile(), profile(saved_plans=True)
        assert old["protocol"] == planned["protocol"]
        assert "saved_plan_method" not in old
        assert planned["saved_plan_method"] == marker
        assert sha(old) != sha(planned)
        assert set(old["source_sha256"]) < set(planned["source_sha256"])
        for path, (previous, current) in compatibility.LEGACY_EQUIVALENTS.items():
            if path in old["source_sha256"]:
                seen.add(path)
                assert old["source_sha256"][path] == previous
                newest = sha((ROOT / path).read_bytes())
                actual, vetted = V3_EQUIVALENTS.get(path, (newest, newest))
                assert newest == vetted
                assert planned["source_sha256"][path] == current
                assert (current, actual) == V2_EQUIVALENTS.get(path, (current, current))
    assert seen == set(compatibility.LEGACY_EQUIVALENTS)


def test_unknown_source_digest_is_not_advertised_as_old_profile(tmp_path, monkeypatch):
    path, (previous, expected_current) = next(iter(compatibility.LEGACY_EQUIVALENTS.items()))
    file = tmp_path / path
    file.parent.mkdir(parents=True)
    file.write_bytes(b"hypothetical unreviewed replacement")
    monkeypatch.setattr(compatibility, "ROOT", tmp_path)
    observed = compatibility.source_hashes((path,), saved_plans=False)
    assert observed == {path: sha(file.read_bytes())}
    assert observed[path] not in (previous, expected_current)


def test_provider_projection_contains_only_links_from_target_plan_without_mutating_the_frozen_context():
    structure = {
        "plans": {
            "active": {
                "section_id": "one",
                "payload": {
                    "rule_ids": ["target-rule"],
                    "source_refs": [
                        {"evidence_id": "target-evidence", "private": "manual source note"}
                    ],
                    "goal": "drafting goal",
                    "key_points": ["unapproved instruction"],
                    "pending_facts": ["date unverified"],
                    "budget_note": "budget not fact",
                },
            },
            "sibling": {
                "section_id": "two",
                "payload": {"goal": "sibling's private plan", "rule_ids": ["not a target link"]},
            },
        }
    }
    baseline = {
        "target": {"section_id": "one"},
        "context": {
            "target": {
                "snapshot_manifest": {
                    "id": "immutable",
                    "authoring_structure": deepcopy(structure),
                },
                "snapshot": {"id": "immutable", "authoring_structure": deepcopy(structure)},
            }
        },
    }
    unchanged = deepcopy(baseline)
    projected = saved_chapter_plans.model_projection(baseline)
    assert baseline == unchanged
    assert projected["context"]["target"] == {
        "snapshot_manifest": {"id": "immutable"},
        "snapshot": {"id": "immutable"},
    }
    assert projected["saved_chapter_plan_links"] == {
        "requirement_ids": ["target-rule"],
        "authority_evidence_ids": ["target-evidence"],
    }
    unrelated = deepcopy(baseline)
    unrelated["target"]["section_id"] = "three"
    assert "saved_chapter_plan_links" not in saved_chapter_plans.model_projection(unrelated)
