"""Controlled local CPU inference from native identities and original /3 bytes."""

from pathlib import Path

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import finite, instant
from packages.package_model_registry import artifact
from packages.storage.private_cas import PrivateContentStore, sha

VERSION = "package-internal-observation/1"


def method_digest():
    sql = Path(__file__).resolve().parents[2] / "deploy/sql/package-model-observation.sql"
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "sql": sha(sql.read_bytes()),
            "artifact_method": artifact.method_digest(),
            "handoff": handoff.method_digest(),
        }
    )


def consume(source, request, store, artifact_dir):
    """source is a native transaction result, never a client-supplied packet."""
    if (
        source.get("schema") != "package-native-observation-source/1"
        or request["method_digest"] != method_digest()
    ):
        artifact.fail()
    document = artifact.validate(source["document"])
    binding = source["binding"]
    if (
        document["model_id"] != request["model_id"]
        or digest(document) != request["artifact_digest"]
        or binding["admission_id"] != request["admission_id"]
    ):
        artifact.fail()
    origin = document["source"]["origin"]
    if (
        binding["origin"] != origin
        or request["reference"]["origin"]
        != {"synthetic": "synthetic_mechanism", "external_evidence": "unqualified_research"}[origin]
    ):
        artifact.fail()
    loaded = handoff.load(store, artifact_dir, **request["reference"])
    metadata = loaded.bundle.context.metadata
    if (
        any(metadata[k] != binding[k] for k in ("bid_id", "scope_id", "scope_digest"))
        or loaded.bundle.context.origin.material["scope"]["manifest"] != binding["scope_manifest"]
        or instant(metadata["input_as_of"]) > instant(binding["submitted_at"])
    ):
        artifact.fail()
    originals = loaded.bundle.context.origin.originals
    expected = {r["document_version_id"]: r for r in binding["originals"]}
    if len(expected) != len(binding["originals"]) or set(originals) != set(expected):
        artifact.fail()
    for key, blob in originals.items():
        if (
            sha(blob) != expected[key]["digest"]
            or len(blob) != expected[key]["byte_size"]
            or key in source["label_document_ids"]
            or sha(blob) in source["label_file_digests"]
        ):
            artifact.fail()
    projected = training.project(loaded)
    if projected["input_digest"] != request["reference"]["expected_input_digest"]:
        artifact.fail()
    candidate = document["source"]["candidate"]
    value = training.predict(candidate["model"], projected["values"])
    return cpu.wire(
        {
            "schema": VERSION,
            "method_digest": method_digest(),
            "source_digest": digest(source),
            "request_digest": digest(request),
            "model_id": document["model_id"],
            "artifact_digest": digest(document),
            "input_digest": projected["input_digest"],
            "projection_digest": projected["digest"],
            "value": value,
            "intervals": {
                level: [
                    max(0, value - finite(item["radius"])),
                    min(100, value + finite(item["radius"])),
                ]
                for level, item in candidate["intervals"].items()
            },
            "mode": "retrospective_internal",
            "origin": origin,
            "formal_eligibility": "unavailable",
            "certification_issued": False,
        }
    )


class LocalExecutor:
    def __init__(self, store_root, artifact_dir):
        self.store_root, self.artifact_dir = store_root, artifact_dir

    def __call__(self, source, request):
        with PrivateContentStore(self.store_root) as store:
            return consume(source, request, store, self.artifact_dir)
