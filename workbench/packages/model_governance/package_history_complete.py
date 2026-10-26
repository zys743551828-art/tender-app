"""Consume /3 only beside an actual purpose-bound native training export.

The runtime obtains the export from its authenticated leased SQL read. The local
reference file contains no labels, group assertions or admission grants.
"""

from pathlib import Path

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_calibration as shape
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_handoff as local
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import instant
from packages.storage.private_cas import PrivateContentStore, sha

VERSION = "package-history-complete-consumer/1"
EXPORT = "package-history-complete-training-export/2"
MAX_REFERENCES = 64


def fail(code):
    local.fail("NATIVE_COMPLETE_" + code)


def method_digest():
    sql = Path(__file__).resolve().parents[2] / "deploy/sql/package-history-complete-material.sql"
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "sql": sha(sql.read_bytes()),
            "handoff": handoff.method_digest(),
            "shape": shape.method_digest(),
            "cpu": cpu.method(),
            "max_references": MAX_REFERENCES,
        }
    )


def training_export(value):
    """Compatibility for the unchanged feature-free CPU on optional /2 installs."""
    if value.get("schema") == EXPORT:
        shape.exact(value, {"schema", "training_export", "material_bindings", "bindings_digest"})
        return value["training_export"]
    return value


def consume(value, raw, *, expected_reference_digest, expected_method_digest, store, artifact_dir):
    # This function's `value` is a trusted-channel input, NOT a public JSON ingest.
    # Only the runtime's connection('train') read supplies it in production code.
    if method_digest() != local.checksum(expected_method_digest):
        fail("METHOD_CHANGED")
    references = shape.decode(raw, expected_reference_digest)
    shape.exact(references, {"version", "method_digest", "cohort_id", "membership_digest", "rows"})
    if references["version"] != VERSION or references["method_digest"] != expected_method_digest:
        fail("REFERENCE_VERSION")
    shape.exact(value, {"schema", "training_export", "material_bindings", "bindings_digest"})
    if value["schema"] != EXPORT:
        fail("NATIVE_EXPORT_REQUIRED")
    bundle = value["training_export"]
    if (
        references["cohort_id"] != bundle["cohort_id"]
        or references["membership_digest"] != bundle["membership_digest"]
    ):
        fail("COHORT_MISMATCH")
    bindings = value["material_bindings"]
    rows = references["rows"]
    if (
        type(rows) is not list
        or not 1 <= len(rows) <= MAX_REFERENCES
        or type(bindings) is not list
        or len(bindings) != len(rows)
        or digest(bindings) != value["bindings_digest"]
    ):
        fail("BINDINGS_CHANGED")
    native = {b["admission_id"]: b for b in bindings}
    train = {r["id"]: r for r in bundle["rows"]}
    if (
        len(native) != len(bindings)
        or len(train) != len(bundle["rows"])
        or set(native) != set(train)
    ):
        fail("DENOMINATOR_CHANGED")
    if bundle["origin"] not in {"synthetic", "external_evidence"}:
        fail("ORIGIN_INVALID")
    expected_origin = (
        "synthetic_mechanism" if bundle["origin"] == "synthetic" else "unqualified_research"
    )
    seen, sources, calls, responses = set(), set(), set(), set()
    receipts = []
    partitions: dict[tuple[str, str], str] = {}
    label_documents = {b["label_document_id"] for b in bindings}
    label_digests = {b["label_file_digest"] for b in bindings}
    for native_row in bundle["rows"]:
        for field in ("project_id", "group_id"):
            key = (field, native_row[field])
            if partitions.setdefault(key, native_row["purpose"]) != native_row["purpose"]:
                fail("PARTITION_LEAK")
    for row in rows:
        shape.exact(row, {"admission_id", "reference"})
        identity = row["admission_id"]
        if identity not in native or identity in seen:
            fail("DENOMINATOR_CHANGED")
        seen.add(identity)
        binding = native[identity]
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
                "label_document_id",
                "label_file_digest",
            },
        )
        native_row = train[identity]
        if (
            binding["origin"] != bundle["origin"]
            or binding["project_id"] != native_row["project_id"]
            or instant(binding["submitted_at"]) != instant(native_row["submitted_at"])
            or native_row["purpose"] not in {"fit", "development", "calibration"}
        ):
            fail("NATIVE_IDENTITY_MISMATCH")
        reference = row["reference"]
        shape.exact(reference, shape.REFERENCE)
        if reference["origin"] != expected_origin:
            fail("ORIGIN_INVALID")
        if reference["expected_input_digest"] in sources:
            fail("INPUT_REUSED")
        sources.add(reference["expected_input_digest"])
        loaded = handoff.load(store, artifact_dir, **reference)
        context = loaded.bundle.context.metadata
        if (
            context["bid_id"] != binding["bid_id"]
            or context["scope_id"] != binding["scope_id"]
            or context["scope_digest"] != binding["scope_digest"]
            or loaded.bundle.context.origin.material["scope"]["manifest"]
            != binding["scope_manifest"]
            or instant(context["input_as_of"]) > instant(binding["submitted_at"])
        ):
            fail("SCOPE_OR_TIME_CHANGED")
        originals = loaded.bundle.context.origin.originals
        expected_originals = {r["document_version_id"]: r for r in binding["originals"]}
        if len(expected_originals) != len(binding["originals"]) or set(originals) != set(
            expected_originals
        ):
            fail("ORIGINALS_CHANGED")
        for key, blob in originals.items():
            expected = expected_originals[key]
            shape.exact(expected, {"document_version_id", "digest", "byte_size"})
            if sha(blob) != expected["digest"] or len(blob) != expected["byte_size"]:
                fail("ORIGINALS_CHANGED")
            if key in label_documents or sha(blob) in label_digests:
                fail("LABEL_IN_MATERIAL")
        for attempt in loaded.attempts:
            if attempt.call_id in calls:
                fail("CALL_REUSED")
            calls.add(attempt.call_id)
            if attempt.generation is not None:
                if attempt.generation.response_id in responses:
                    fail("RESPONSE_REUSED")
                responses.add(attempt.generation.response_id)
        receipts.append(
            {
                "admission_id": identity,
                "proof_id": binding["proof_id"],
                "context_digest": binding["context_digest"],
                "source_commit": reference["source_commit"],
                "artifact_digest": reference["expected_artifact_digest"],
                "input_digest": reference["expected_input_digest"],
                "features_digest": digest(loaded.features),
            }
        )
    # Labels are consumed solely by the unchanged historical CPU, after material
    # matching. Never pass target values into the /3 serializer or aggregation.
    result = cpu.train(bundle)
    result["complete_material_consumer"] = {
        "version": VERSION,
        "method_digest": expected_method_digest,
        "reference_digest": expected_reference_digest,
        "bindings_digest": value["bindings_digest"],
        "receipts": receipts,
        "features_used_for_fit": False,
        "formal_prediction": None,
        **handoff.FLAGS,
    }
    return result


def run(value, config):
    raw = local.private_read(config["references"], maximum=shape.MAX_BYTES)
    with PrivateContentStore(config["material_store"]) as store:
        result = consume(
            value,
            raw,
            expected_reference_digest=config["reference_digest"],
            expected_method_digest=config["method_digest"],
            store=store,
            artifact_dir=config["artifact_dir"],
        )
        # The DB result binds this exact file digest. No second result store or
        # native eligibility grant is created. Orphan CAS bytes on lost lease are inert.
        if store.put_object(raw) != sha(raw) or store.get_object(sha(raw)) != raw:
            fail("REFERENCE_STORAGE_CHANGED")
        canonical(result)
        return result
