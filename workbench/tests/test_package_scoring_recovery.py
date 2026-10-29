"""Purpose credentials remain isolated before any reconciliation connection."""

import pytest

from deploy.package_scoring_reconcile import environment


def test_profile_builds_an_explicit_purpose_only_environment(tmp_path):
    profile = tmp_path / "reconciler.env"
    profile.write_text("PACKAGE_SCORE_RECONCILIATION_DSN='host=localhost dbname=synthetic'\n")
    profile.chmod(0o600)
    assert environment(profile) == {
        "PACKAGE_SCORE_RECONCILIATION_DSN": "host=localhost dbname=synthetic",
        "WORKBENCH_ENV_FILE": "/dev/null",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        "API_DATABASE_DSN=synthetic\n",
        "PACKAGE_SCORE_RECONCILIATION_DSN=synthetic\nAPI_DATABASE_DSN=synthetic\n",
        "PACKAGE_SCORE_RECONCILIATION_DSN=synthetic\nPACKAGE_SCORE_RECONCILIATION_DSN=another\n",
        "PACKAGE_SCORE_RECONCILIATION_DSN=\n",
        "PACKAGE_SCORE_RECONCILIATION_DSN=one two\n",
        "PACKAGE_SCORE_RECONCILIATION_DSN='unterminated\n",
    ],
)
def test_other_purpose_empty_or_ambiguous_profiles_are_rejected(tmp_path, value):
    profile = tmp_path / "reconciler.env"
    profile.write_text(value)
    profile.chmod(0o600)
    with pytest.raises(ValueError):
        environment(profile)


def test_profile_rejects_symlink_and_broad_permissions(tmp_path):
    profile = tmp_path / "reconciler.env"
    profile.write_text("PACKAGE_SCORE_RECONCILIATION_DSN=synthetic\n")
    profile.chmod(0o644)
    with pytest.raises(ValueError):
        environment(profile)
    profile.chmod(0o600)
    link = tmp_path / "linked.env"
    link.symlink_to(profile)
    with pytest.raises(ValueError):
        environment(link)
