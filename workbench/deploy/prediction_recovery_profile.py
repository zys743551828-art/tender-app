"""Explicit /2 extension of the existing offline recovery, including private CAS refs."""

import re
from uuid import NAMESPACE_URL, uuid5

from deploy.backups import run

FORMAT = "tender-extended-offline-recovery/2"
SQL = tuple(
    "deploy/sql/" + name + ".sql"
    for name in (
        "material-qualification",
        "material-qualified-execution",
        "package-historical-admission",
        "package-historical-research",
        "package-history-complete-material",
        "package-history-feature-final",
        "package-history-feature-evaluation",
        "package-history-feature-dispatch",
        "package-history-exposure-bridge",
        "package-history-dispatch",
        "package-history-directory",
        "package-model-registry",
        "package-model-admission",
        "package-model-observation",
        "package-model-route-v2",
        "package-business-shadow",
        "package-model-certification",
        "package-formal-prediction",
        "package-prediction-selection",
    )
)
RELATIONS = (
    "package_model_registry.registrations",
    "package_model_admission.protocols",
    "package_model_admission.reports",
    "package_model_admission.certificates",
    "package_model_observation.events",
    "package_model_route.events",
    "package_prediction.results",
)


def private_references(c):
    """Capture opaque references in the same exported snapshot as commands/effects."""
    rows = c.execute(
        "SELECT payload->>'input_ref' FROM design.audit_entries "
        "WHERE event_type='package.prediction.task_accepted' UNION "
        "SELECT e.result->>'result_ref' FROM design.effect_receipts e "
        "JOIN design.operations o ON o.id=e.operation_id "
        "JOIN design.step_receipts s ON s.operation_id=e.operation_id AND s.step_key=e.effect_key "
        "WHERE o.handler_version='package-prediction/1' AND e.effect_key='compute-package-prediction' "
        "AND s.state='succeeded'"
    ).fetchall()
    refs = [r[0] for r in rows]
    if any(not isinstance(ref, str) or not re.fullmatch("[a-f0-9]{64}", ref) for ref in refs):
        raise run.BackupError("PREDICTION_RECOVERY_PRIVATE_REFERENCE_INVALID")
    return sorted(set(refs))


def object_rows(references, client, bucket, registered):
    if client is None or not bucket:
        raise run.BackupError("PREDICTION_RECOVERY_OBJECT_PORT_REQUIRED")
    keys = {r[2]: r for r in registered}
    rows = []
    total = sum(r[3] for r in registered)
    for ref in references:
        key = "blobs/" + ref
        head = client.head_object(Bucket=bucket, Key=key)
        size = head["ContentLength"]
        if type(size) is not int or not 0 < size <= 32 * 1024 * 1024:
            raise run.BackupError("PREDICTION_RECOVERY_PRIVATE_OBJECT_SIZE")
        if key in keys:
            if keys[key][1] != ref or keys[key][3] != size:
                raise run.BackupError("PREDICTION_RECOVERY_OBJECT_IDENTITY_CHANGED")
            continue
        total += size
        if total > run.MAX_ARCHIVE_BYTES:
            raise run.BackupError("ARCHIVE_OBJECT_BUDGET_EXCEEDED")
        rows.append(
            (
                str(uuid5(NAMESPACE_URL, "prediction-private:" + key)),
                ref,
                key,
                size,
                "application/json",
            )
        )
    return rows
