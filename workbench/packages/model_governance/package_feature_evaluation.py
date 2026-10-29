"""Evaluate one immutable research candidate after native committed exposure.

No fitting, source selection, model replacement, credentials or exposure flags.
The runtime validates predictions before open_final and reads labels only in a
new committed transaction. This consumer cannot authorize its own inputs.
"""

from math import isclose
from pathlib import Path
from uuid import UUID

from packages.domain.review_identity import digest
from packages.model_governance import evaluation
from packages.model_governance import package_complete_calibration as shape
from packages.model_governance import package_feature_final as frozen
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import GovernanceError, finite
from packages.storage.private_cas import sha

VERSION = "package-history-feature-evaluation/1"
INPUT = "package-history-feature-evaluation-input/1"


def fail(code):
    raise GovernanceError(
        "PACKAGE_FEATURE_EVALUATION_" + code, "Frozen independent evaluation rejected"
    )


def method_digest():
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "sql": sha(
                (
                    Path(__file__).resolve().parents[2]
                    / "deploy/sql/package-history-feature-evaluation.sql"
                ).read_bytes()
            ),
            "freeze_method": frozen.method_digest(),
            "cpu_method": cpu.method(),
        }
    )


def validate(packet, predictions):
    """Label-free check, required BEFORE attempting the irreversible exposure."""
    if packet.get("schema") != frozen.INPUT or not isinstance(predictions, dict):
        fail("PREDICTIONS_REQUIRED")
    shape.exact(
        predictions,
        {
            "schema",
            "cohort_id",
            "membership_digest",
            "candidate_digest",
            "model_digest",
            "method_digest",
            "reference_digest",
            "bindings_digest",
            "manifest_digest",
            "rows",
            "research_only",
            "formal_prediction",
            "evaluation_status",
        },
    )
    candidate = packet["candidate"]
    if (
        predictions["schema"] != frozen.VERSION
        or predictions["method_digest"] != frozen.method_digest()
        or candidate.get("version") != training.VERSION
        or candidate.get("status") != "research_candidate"
        or candidate.get("method_digest") != training.method()["digest"]
        or candidate.get("model_digest") != digest(candidate.get("model"))
        or predictions["model_digest"] != candidate["model_digest"]
        or predictions["candidate_digest"] != digest(candidate)
        or packet["candidate_digest"] != digest(candidate)
        or candidate["membership_digest"] != packet["membership_digest"]
        or candidate["origin"] != packet["origin"]
        or predictions["research_only"] is not True
        or predictions["formal_prediction"] is not None
        or predictions["evaluation_status"] != "not_implemented"
        or any(
            predictions[k] != packet[k]
            for k in ("cohort_id", "membership_digest", "bindings_digest", "manifest_digest")
        )
        or digest(packet["material_bindings"]) != packet["bindings_digest"]
        or digest(packet["manifest"]) != packet["manifest_digest"]
    ):
        fail("IDENTITY_CHANGED")
    members = {r["id"]: r for r in packet["manifest"]}
    bindings = {r["admission_id"]: r for r in packet["material_bindings"]}
    rows = predictions["rows"]
    if (
        type(rows) is not list
        or not 1 <= len(rows) <= 64
        or len(members) != len(packet["manifest"])
        or len(bindings) != len(packet["material_bindings"])
        or set(bindings) != set(members)
        or len(rows) != len(members)
        or {r["id"] for r in rows} != set(members)
    ):
        fail("DENOMINATOR_CHANGED")
    seen = {r["input_digest"] for r in packet["training_inputs"]}
    projects = {r["project_id"] for r in packet["training_members"]}
    groups = {r["group_id"] for r in packet["training_members"]}
    for row in rows:
        shape.exact(row, {"id", "status", "prediction", "projection", "receipt"})
        member, binding = members[row["id"]], bindings[row["id"]]
        if member["status"] not in {"succeeded", "rejected", "unlabeled"}:
            fail("STATUS_INVALID")
        if member["status"] != "succeeded":
            if row["status"] != member["status"] or any(
                row[k] is not None for k in ("prediction", "projection", "receipt")
            ):
                fail("EXCLUSION_CHANGED")
            continue
        if (
            member["project_id"] in projects
            or member["group_id"] in groups
            or member["project_id"] != binding["project_id"]
        ):
            fail("PARTITION_LEAK")
        receipt = row["receipt"]
        shape.exact(
            receipt,
            {"proof_id", "context_digest", "input_digest", "artifact_digest", "source_commit"},
        )
        if (
            any(receipt[k] != binding[k] for k in ("proof_id", "context_digest"))
            or receipt["input_digest"] in seen
        ):
            fail("INPUT_CHANGED")
        seen.add(receipt["input_digest"])
        if row["status"] == "failed":
            if row["prediction"] is not None or row["projection"] is not None:
                fail("FAILURE_CHANGED")
            continue
        if row["status"] != "succeeded":
            fail("STATUS_INVALID")
        projection = row["projection"]
        shape.exact(
            projection,
            {"schema", "method_digest", "input_digest", "features_digest", "values", "digest"},
        )
        if (
            projection["schema"] != training.SCHEMA
            or projection["method_digest"] != candidate["method_digest"]
            or projection["input_digest"] != receipt["input_digest"]
            or projection["digest"]
            != digest({k: v for k, v in projection.items() if k != "digest"})
            or not isclose(
                finite(row["prediction"], lower=0, upper=100),
                training.predict(candidate["model"], projection["values"]),
                rel_tol=0,
                abs_tol=1e-8,
            )
        ):
            fail("PREDICTION_CHANGED")
    return candidate


def evaluate(bundle):
    """Only the runtime's post-commit read_final supplies this export."""
    feature = bundle["feature_final"]
    shape.exact(
        feature,
        {
            "version",
            "exposure_id",
            "input",
            "input_digest",
            "predictions",
            "predictions_digest",
            "candidate_digest",
        },
    )
    if feature["version"] != INPUT or str(UUID(feature["exposure_id"])) != feature["exposure_id"]:
        fail("EXPOSURE_INVALID")
    packet, predictions = feature["input"], feature["predictions"]
    if (
        feature["input_digest"] != digest(packet)
        or feature["predictions_digest"] != digest(predictions)
        or feature["candidate_digest"] != packet["candidate_digest"]
    ):
        fail("SEAL_CHANGED")
    candidate = validate(packet, predictions)
    baseline = cpu.evaluate({k: v for k, v in bundle.items() if k != "feature_final"})
    if (
        any(packet[k] != bundle[k] for k in ("cohort_id", "membership_digest", "origin"))
        or [{k: v for k, v in row.items() if k != "target"} for row in bundle["labels"]]
        != packet["manifest"]
    ):
        fail("LABEL_IDENTITY_CHANGED")
    by_id = {r["id"]: r for r in predictions["rows"]}
    rows = []
    for label in bundle["labels"]:
        row = by_id[label["id"]]
        numeric = label | {
            "status": row["status"],
            "prediction": row["prediction"],
            "method": training.VERSION,
        }
        if row["status"] == "succeeded":
            numeric.update(
                target=finite(label["target"], lower=0, upper=100),
                prediction=finite(row["prediction"], lower=0, upper=100),
                maximum=finite(label["maximum"], lower=1e-9, upper=1e9),
            )
        rows.append(numeric)
    report = evaluation.metrics(
        rows,
        expected_ids=sorted(by_id),
        intervals=candidate["intervals"],
        seed=bundle["protocol"]["seed"],
        bootstrap_iterations=bundle["protocol"]["bootstrap_iterations"],
        baseline_predictions=bundle["predictions"]["baseline_predictions"],
    )
    result = {
        "version": VERSION,
        "cohort_id": bundle["cohort_id"],
        "origin": bundle["origin"],
        "membership_digest": bundle["membership_digest"],
        "method_digest": method_digest(),
        "freeze_method_digest": predictions["method_digest"],
        "candidate_digest": feature["candidate_digest"],
        "model_digest": candidate["model_digest"],
        "predictions_digest": feature["predictions_digest"],
        "labels_digest": bundle["labels_digest"],
        "input_digest": feature["input_digest"],
        "exposure_id": feature["exposure_id"],
        "report": cpu.wire(report),
        "research_only": True,
        "formal_prediction": None,
        "acceptance_decision": "unavailable",
        "provider_requests": 0,
        "paid_calls": 0,
    }
    return baseline | {"feature_final_evaluation": result}
