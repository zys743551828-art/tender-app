"""Label-free /3 final prediction stage, authorized exclusively by a native lease.

No local export can authorize exposure. The optional fresh SQL extension stores
these predictions and deliberately denies feature final evaluation until its
separate versioned consumer exists. Old constant-baseline methods are unchanged.
"""

from pathlib import Path

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_calibration as shape
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_handoff as files
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_complete as native_complete
from packages.model_governance.common import GovernanceError, instant
from packages.storage.private_cas import PrivateContentStore, sha

VERSION = "package-history-feature-final-predictions/1"
INPUT = "package-history-feature-final-input/1"
REFERENCE = "package-history-feature-final-references/1"


def fail(code):
    raise GovernanceError("PACKAGE_FEATURE_FINAL_" + code, "Frozen final prediction rejected")


def method_digest():
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "sql": sha(
                (
                    Path(__file__).resolve().parents[2]
                    / "deploy/sql/package-history-feature-final.sql"
                ).read_bytes()
            ),
            "training_method": training.method()["digest"],
            "evaluation": "not_implemented",
        }
    )


def consume(packet, raw, *, expected_reference_digest, expected_method_digest, store, artifact_dir):
    """Packet must come from claim_job on the dedicated evaluate connection."""
    if files.checksum(expected_method_digest) != method_digest():
        fail("METHOD_CHANGED")
    shape.exact(
        packet,
        {
            "schema",
            "cohort_id",
            "membership_digest",
            "origin",
            "candidate",
            "candidate_digest",
            "manifest",
            "manifest_digest",
            "material_bindings",
            "bindings_digest",
            "training_inputs",
            "training_members",
            "forbidden_label_sources",
        },
    )
    if packet["schema"] != INPUT or packet["origin"] not in {"synthetic", "external_evidence"}:
        fail("NATIVE_INPUT_REQUIRED")
    candidate = packet["candidate"]
    if (
        candidate.get("version") != training.VERSION
        or candidate.get("status") != "research_candidate"
        or candidate.get("method_digest") != training.method()["digest"]
        or candidate.get("membership_digest") != packet["membership_digest"]
        or candidate.get("origin") != packet["origin"]
        or candidate.get("model_digest") != digest(candidate.get("model"))
        or digest(candidate) != packet["candidate_digest"]
        or candidate.get("formal_prediction") is not None
        or candidate.get("final_test_consumption") != "not_implemented"
        or any(candidate.get(key) is not False for key in handoff.FLAGS)
    ):
        fail("CANDIDATE_CHANGED")
    refs = shape.decode(raw, expected_reference_digest)
    shape.exact(refs, {"version", "cohort_id", "membership_digest", "candidate_digest", "rows"})
    if refs["version"] != REFERENCE or any(
        refs[key] != packet[key] for key in ("cohort_id", "membership_digest", "candidate_digest")
    ):
        fail("REFERENCE_CHANGED")
    manifest, bindings = packet["manifest"], packet["material_bindings"]
    if (
        type(manifest) is not list
        or not 1 <= len(manifest) <= 64
        or type(bindings) is not list
        or len(bindings) != len(manifest)
        or type(refs["rows"]) is not list
        or len(refs["rows"]) != len(manifest)
        or digest(manifest) != packet["manifest_digest"]
        or digest(bindings) != packet["bindings_digest"]
    ):
        fail("DENOMINATOR_CHANGED")
    members = {r["id"]: r for r in manifest}
    native = {r["admission_id"]: r for r in bindings}
    references = {r["admission_id"]: r for r in refs["rows"]}
    if (
        len(members) != len(manifest)
        or len(native) != len(bindings)
        or len(references) != len(refs["rows"])
        or set(members) != set(native)
        or set(native) != set(references)
    ):
        fail("DENOMINATOR_CHANGED")
    projects = {r["project_id"] for r in packet["training_members"]}
    groups = {r["group_id"] for r in packet["training_members"]}
    inputs = {r["input_digest"] for r in packet["training_inputs"]}
    label_ids = {r["id"] for r in packet["forbidden_label_sources"]}
    label_digests = {r["digest"] for r in packet["forbidden_label_sources"]}
    # Reopen the exact training reference CAS recorded by the native trainer;
    # changing an input digest must not hide a reused provider call/response.
    training_raw = store.get_object(candidate["source_digest"])
    training_refs = shape.decode(training_raw, candidate["source_digest"])
    shape.exact(
        training_refs, {"version", "method_digest", "cohort_id", "membership_digest", "rows"}
    )
    if (
        training_refs["version"] != native_complete.VERSION
        or training_refs["method_digest"] != native_complete.method_digest()
        or any(training_refs[k] != packet[k] for k in ("cohort_id", "membership_digest"))
    ):
        fail("TRAINING_REFERENCE_CHANGED")
    prior_inputs = {r["admission_id"]: r for r in packet["training_inputs"]}
    if (
        len(prior_inputs) != len(packet["training_inputs"])
        or len(training_refs["rows"]) != len(prior_inputs)
        or {r["admission_id"] for r in training_refs["rows"]} != set(prior_inputs)
    ):
        fail("TRAINING_REFERENCE_CHANGED")
    calls, responses = set(), set()
    for row in training_refs["rows"]:
        shape.exact(row, {"admission_id", "reference"})
        reference = row["reference"]
        shape.exact(reference, shape.REFERENCE)
        receipt = prior_inputs[row["admission_id"]]
        if any(
            reference[key] != receipt[other]
            for key, other in (
                ("expected_input_digest", "input_digest"),
                ("expected_artifact_digest", "artifact_digest"),
                ("source_commit", "source_commit"),
            )
        ):
            fail("TRAINING_REFERENCE_CHANGED")
        historical = handoff.load(store, artifact_dir, **reference)
        for attempt in historical.attempts:
            if attempt.call_id in calls:
                fail("CALL_REUSED")
            calls.add(attempt.call_id)
            if attempt.generation is not None:
                if attempt.generation.response_id in responses:
                    fail("RESPONSE_REUSED")
                responses.add(attempt.generation.response_id)
    output = []
    for identity in sorted(members):
        member, binding, row = members[identity], native[identity], references[identity]
        shape.exact(
            member,
            {
                "id",
                "project_id",
                "group_id",
                "method",
                "engineering_type",
                "maximum",
                "status",
                "reason",
            },
        )
        shape.exact(
            binding,
            {
                "admission_id",
                "proof_id",
                "context_digest",
                "bid_id",
                "scope_id",
                "scope_digest",
                "scope_manifest",
                "project_id",
                "submitted_at",
                "origin",
                "originals",
            },
        )
        shape.exact(row, {"admission_id", "reference"})
        if member["status"] not in {"succeeded", "rejected", "unlabeled"}:
            fail("STATUS_INVALID")
        # Excluded overlapping groups stay in the denominator, never projected.
        if member["status"] != "succeeded":
            if row["reference"] is not None:
                fail("EXCLUDED_REFERENCE")
            output.append(
                {
                    "id": identity,
                    "status": member["status"],
                    "prediction": None,
                    "projection": None,
                    "receipt": None,
                }
            )
            continue
        if member["project_id"] in projects or member["group_id"] in groups:
            fail("PARTITION_LEAK")
        if binding["project_id"] != member["project_id"] or binding["origin"] != packet["origin"]:
            fail("IDENTITY_CHANGED")
        reference = row["reference"]
        shape.exact(reference, shape.REFERENCE)
        origin = (
            "synthetic_mechanism" if packet["origin"] == "synthetic" else "unqualified_research"
        )
        if reference["origin"] != origin or reference["expected_input_digest"] in inputs:
            fail("INPUT_REUSED_OR_ORIGIN_CHANGED")
        inputs.add(reference["expected_input_digest"])
        loaded = handoff.load(store, artifact_dir, **reference)
        context = loaded.bundle.context.metadata
        if (
            any(context[key] != binding[key] for key in ("bid_id", "scope_id", "scope_digest"))
            or loaded.bundle.context.origin.material["scope"]["manifest"]
            != binding["scope_manifest"]
            or instant(context["input_as_of"]) > instant(binding["submitted_at"])
        ):
            fail("SCOPE_OR_TIME_CHANGED")
        originals = loaded.bundle.context.origin.originals
        expected = {r["document_version_id"]: r for r in binding["originals"]}
        if len(expected) != len(binding["originals"]) or set(expected) != set(originals):
            fail("ORIGINALS_CHANGED")
        for key, blob in originals.items():
            shape.exact(expected[key], {"document_version_id", "digest", "byte_size"})
            if sha(blob) != expected[key]["digest"] or len(blob) != expected[key]["byte_size"]:
                fail("ORIGINALS_CHANGED")
            if key in label_ids or sha(blob) in label_digests:
                fail("LABEL_IN_MATERIAL")
        for attempt in loaded.attempts:
            if attempt.call_id in calls:
                fail("CALL_REUSED")
            calls.add(attempt.call_id)
            if attempt.generation is not None:
                if attempt.generation.response_id in responses:
                    fail("RESPONSE_REUSED")
                responses.add(attempt.generation.response_id)
        receipt = {
            "proof_id": binding["proof_id"],
            "context_digest": binding["context_digest"],
            "input_digest": reference["expected_input_digest"],
            "artifact_digest": reference["expected_artifact_digest"],
            "source_commit": reference["source_commit"],
        }
        try:
            projection = training.project(loaded)
        except training.ProjectionUnavailable:
            output.append(
                {
                    "id": identity,
                    "status": "failed",
                    "prediction": None,
                    "projection": None,
                    "receipt": receipt,
                }
            )
        else:
            output.append(
                {
                    "id": identity,
                    "status": "succeeded",
                    "prediction": str(training.predict(candidate["model"], projection["values"])),
                    "projection": projection,
                    "receipt": receipt,
                }
            )
    return {
        "schema": VERSION,
        "cohort_id": packet["cohort_id"],
        "membership_digest": packet["membership_digest"],
        "candidate_digest": packet["candidate_digest"],
        "model_digest": candidate["model_digest"],
        "method_digest": expected_method_digest,
        "reference_digest": expected_reference_digest,
        "bindings_digest": packet["bindings_digest"],
        "manifest_digest": packet["manifest_digest"],
        "rows": output,
        "research_only": True,
        "formal_prediction": None,
        "evaluation_status": "not_implemented",
    }


def run(packet, config):
    raw = files.private_read(config["references"], maximum=shape.MAX_BYTES)
    with PrivateContentStore(config["material_store"]) as store:
        result = consume(
            packet,
            raw,
            expected_reference_digest=config["reference_digest"],
            expected_method_digest=config["method_digest"],
            store=store,
            artifact_dir=config["artifact_dir"],
        )
        if store.put_object(raw) != sha(raw):
            fail("REFERENCE_STORAGE_CHANGED")
        return result
