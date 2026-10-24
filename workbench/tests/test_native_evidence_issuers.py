"""Native issuer references cannot alias file CAS commits or grant qualification."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.model_governance import package_native_evidence_issuers as issuer


def reference():
    return {
        "version": "package-native-evidence-attestation-reference/2",
        **{key: "a" * 64 for key in issuer.REF_FIELDS},
        "registration_id": str(uuid4()),
        "storage_record_id": str(uuid4()),
    }


def test_native_reference_has_no_file_commit_or_qualification_fields():
    value = reference()
    issuer._reference(value)
    assert not any("commit" in key for key in value)


@pytest.mark.parametrize(
    "mutation", ["v1", "cas", "zero", "storage_id", "registration_id", "grant", "missing"]
)
def test_native_reference_rejects_legacy_malformed_or_qualification(mutation):
    value = deepcopy(reference())
    if mutation == "v1":
        value["version"] = "package-scope-review-attestation-reference/1"
    elif mutation == "cas":
        value["findings_commit_digest"] = "b" * 64
    elif mutation == "zero":
        value["findings_digest"] = "0" * 64
    elif mutation in {"storage_id", "registration_id"}:
        value["storage_record_id" if mutation == "storage_id" else mutation] = "invalid"
    elif mutation == "grant":
        value["necessary_scope_verified"] = True
    else:
        value.pop("native_store_method_digest")
    with pytest.raises(issuer.NativeEvidenceIssuerError):
        issuer._reference(value)
