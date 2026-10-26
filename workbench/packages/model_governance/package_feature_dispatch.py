"""Opt-in fixed reference plans for the existing bounded history dispatcher.

A local plan is a requested configuration, never native authority. The existing
owned lease must bind it in SQL before material consumption or final exposure.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_calibration as shape
from packages.model_governance import package_feature_evaluation as evaluation
from packages.model_governance import package_feature_final as final
from packages.model_governance import package_feature_handoff as files
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_complete as complete
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore, sha

VERSION = "package-history-feature-dispatch-plan/1"
BINDING = "package-history-feature-dispatch-binding/1"
MAX_JOBS = 64


def fail(code):
    raise GovernanceError("PACKAGE_FEATURE_DISPATCH_" + code, "Frozen feature dispatch rejected")


def methods():
    root = Path(__file__).resolve().parents[2]
    return {
        "complete": complete.method_digest(),
        "training": training.method()["digest"],
        "final": final.method_digest(),
        "evaluation": evaluation.method_digest(),
        "dispatch": digest(
            {
                "version": VERSION,
                "source": sha(Path(__file__).read_bytes()),
                "runtime": sha(Path(__file__).with_name("package_history_runtime.py").read_bytes()),
                "sql": sha((root / "deploy/sql/package-history-feature-dispatch.sql").read_bytes()),
            }
        ),
    }


def identity(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            fail("IDENTITY_INVALID")
    except (ValueError, AttributeError):
        fail("IDENTITY_INVALID")
    return value


def binding(row, purpose):
    return {
        "schema": BINDING,
        "job_id": row["job_id"],
        "cohort_id": row["cohort_id"],
        "membership_digest": row["membership_digest"],
        "purpose": purpose,
        "reference_digest": row["reference_digest"],
        "candidate_digest": row["candidate_digest"],
        "methods": deepcopy(row["methods"]),
    }


def validate_binding(value, purpose, job_id):
    shape.exact(
        value,
        {
            "schema",
            "job_id",
            "cohort_id",
            "membership_digest",
            "purpose",
            "reference_digest",
            "candidate_digest",
            "methods",
        },
    )
    if (
        value["schema"] != BINDING
        or purpose not in {"train", "evaluate"}
        or value["purpose"] != purpose
        or value["job_id"] != str(job_id)
        or value["methods"] != methods()
    ):
        fail("BINDING_OR_METHOD_CHANGED")
    identity(value["job_id"])
    identity(value["cohort_id"])
    files.checksum(value["membership_digest"])
    files.checksum(value["reference_digest"])
    if purpose == "train":
        if value["candidate_digest"] is not None:
            fail("CANDIDATE_INVALID")
    else:
        files.checksum(value["candidate_digest"])


def verify_reference(value, config):
    raw = files.private_read(config["references"], maximum=shape.MAX_BYTES)
    ref = shape.decode(raw, value["reference_digest"])
    if any(ref.get(key) != value[key] for key in ("cohort_id", "membership_digest")):
        fail("REFERENCE_IDENTITY_CHANGED")
    if value["purpose"] == "train":
        shape.exact(ref, {"version", "method_digest", "cohort_id", "membership_digest", "rows"})
        if (
            ref["version"] != complete.VERSION
            or ref["method_digest"] != value["methods"]["complete"]
        ):
            fail("REFERENCE_METHOD_CHANGED")
    else:
        shape.exact(ref, {"version", "cohort_id", "membership_digest", "candidate_digest", "rows"})
        if (
            ref["version"] != final.REFERENCE
            or ref["candidate_digest"] != value["candidate_digest"]
        ):
            fail("REFERENCE_CANDIDATE_CHANGED")
    if (
        config["reference_digest"] != value["reference_digest"]
        or config["method_digest"]
        != value["methods"]["complete" if value["purpose"] == "train" else "final"]
    ):
        fail("CONFIGURATION_CHANGED")
    # Exact bytes are recoverable independently of the path. This writes no
    # native grant and never opens labels or provider connections.
    with PrivateContentStore(config["material_store"]) as store:
        if store.put_object(raw) != value["reference_digest"]:
            fail("REFERENCE_STORAGE_CHANGED")
    return raw


@dataclass(frozen=True)
class Plan:
    purpose: str
    raw: bytes
    digest: str

    def run(self, job_id, generation):
        from packages.model_governance import package_history_runtime as runtime

        # Decode the frozen bytes anew; no caller can mutate a previously
        # returned mapping, and current method drift is checked on every job.
        document = shape.decode(self.raw, self.digest)
        matches = [row for row in document["jobs"] if row["job_id"] == str(job_id)]
        if len(matches) != 1:
            fail("JOB_NOT_CONFIGURED")
        row = matches[0]
        pinned = binding(row, self.purpose)
        validate_binding(pinned, self.purpose, job_id)
        config = {key: Path(row[key]) for key in ("references", "material_store", "artifact_dir")}
        config.update(
            reference_digest=row["reference_digest"],
            method_digest=row["methods"]["complete" if self.purpose == "train" else "final"],
        )
        verify_reference(pinned, config)
        with PrivateContentStore(config["material_store"]) as store:
            if store.put_object(self.raw) != self.digest:
                fail("PLAN_STORAGE_CHANGED")
        if self.purpose == "train":
            return runtime.run(
                self.purpose,
                job_id,
                generation,
                dispatch_binding=pinned,
                complete_material=config,
                feature_training_method=row["methods"]["training"],
            )
        return runtime.run(
            self.purpose, job_id, generation, dispatch_binding=pinned, final_material=config
        )


def load(path, expected_digest, purpose):
    raw = files.private_read(path, maximum=shape.MAX_BYTES)
    value = shape.decode(raw, expected_digest)
    shape.exact(value, {"version", "purpose", "jobs"})
    if (
        value["version"] != VERSION
        or purpose not in {"train", "evaluate"}
        or value["purpose"] != purpose
        or type(value["jobs"]) is not list
        or not 1 <= len(value["jobs"]) <= MAX_JOBS
    ):
        fail("PLAN_INVALID")
    seen = set()
    for row in value["jobs"]:
        shape.exact(
            row,
            {
                "job_id",
                "cohort_id",
                "membership_digest",
                "reference_digest",
                "candidate_digest",
                "methods",
                "references",
                "material_store",
                "artifact_dir",
            },
        )
        validate_binding(binding(row, purpose), purpose, row["job_id"])
        if row["job_id"] in seen:
            fail("DUPLICATE_JOB")
        seen.add(row["job_id"])
        for key in ("references", "material_store", "artifact_dir"):
            if (
                not isinstance(row[key], str)
                or "\x00" in row[key]
                or not Path(row[key]).is_absolute()
                or ".." in Path(row[key]).parts
            ):
                fail("PATH_INVALID")
    return Plan(purpose, raw, sha(raw))
