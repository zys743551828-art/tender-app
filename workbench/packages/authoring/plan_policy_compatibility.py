"""Freeze the known preceding no-plan policy when only its new variant changed.

Unknown execution bytes are never relabeled as the previous implementation.
Editing one of the mapped files subsequently requires a new compatibility review.
"""

from packages.authoring import bound_format_scope, combined_authoring_scope
from packages.authoring.bound_format_policy_compatibility import V2_EQUIVALENTS
from packages.authoring.combined_scope_policy_compatibility import V3_EQUIVALENTS
from packages.authoring.saved_chapter_plans import DDL, HELPER
from packages.domain.runtime import ROOT, sha

COMPATIBILITY = "packages/authoring/plan_policy_compatibility.py"
# Source bytes at the checked no-plan base (b640791) and this reviewed dual-path implementation.
LEGACY_EQUIVALENTS: dict[str, tuple[str, str]] = {
    "packages/authoring/package_admission.py": (
        "826b93218d28457365061ead68efa5627d68c78135abeaea255a120cb639954d",
        "02f7906fb29126f12b6cd3bd56b1a2c7daa316b0e5c737acf76b03c2a8b20fdd",
    ),
    "packages/authoring/package_generation.py": (
        "f1db33e883083dc146d2ca6a514a236e1ac687a573fba3259405f0b72fb70e22",
        "215c5a2f094d8a429ba3fc4555bb8348edba95a76e210d7852ec956976f7de69",
    ),
    "packages/authoring/package_input_observation.py": (
        "eb2c1839d5a43f8abc31a4c5b12708a8818845643da0030344c3d9a941c08bec",
        "5415ed991a48e4f868a1d90aec2028b48efb18f0d36ff97fde7834d17fee3bf5",
    ),
    "packages/authoring/package_job_authority.py": (
        "fed8775ce3a99e00f6867b39f6229b3160ca594bb95215d65894b9f00e8232dc",
        "0db40a19ca4c3497e540bb56aedef1d9defe42f8d9ef897282b83b29b43018dc",
    ),
    "packages/authoring/package_jobs.py": (
        "85edad371e07c2ed1615e01f9b96c92cba6b9f688414602475cacdd4d1716717",
        "3f72f992f086995192bd831d770dc5d3f9ef7c56acae11c298536d72786e38e5",
    ),
}


def source_hashes(paths, *, saved_plans, bound_format=False):
    combined = saved_plans and bound_format
    if saved_plans or bound_format:
        paths = (
            *paths,
            HELPER,
            DDL,
            COMPATIBILITY,
            "packages/authoring/planning.py",
            "packages/authoring/format_bindings.py",
        )
    if bound_format:
        paths = (
            *paths,
            bound_format_scope.HELPER,
            bound_format_scope.DDL,
            "packages/authoring/bound_format_policy_compatibility.py",
            "packages/domain/fact_sets.py",
            "packages/domain/human_decisions.py",
            "packages/domain/review_data.py",
        )
    if combined:
        paths = (
            *paths,
            combined_authoring_scope.HELPER,
            combined_authoring_scope.DDL,
            "packages/authoring/combined_scope_policy_compatibility.py",
        )
    values = {name: sha((ROOT / name).read_bytes()) for name in paths}
    if combined:
        return values
    for name, (old, equivalent) in V3_EQUIVALENTS.items():
        if values.get(name) == equivalent:
            values[name] = old
    if bound_format:
        return values
    for name, (old, equivalent) in V2_EQUIVALENTS.items():
        if values.get(name) == equivalent:
            values[name] = old
    if not saved_plans:
        for name, (old, equivalent) in LEGACY_EQUIVALENTS.items():
            if values.get(name) == equivalent:
                values[name] = old
    return values
