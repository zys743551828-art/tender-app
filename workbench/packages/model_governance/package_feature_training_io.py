"""Feature candidates in existing local and native result sinks, without new grants."""

import os

from packages.domain.review_identity import canonical
from packages.model_governance import package_complete_calibration as local
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_handoff as files
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_complete as native
from packages.model_governance import package_history_cpu as cpu
from packages.storage.private_cas import PrivateContentStore, sha


def projections(store, artifact_dir, rows):
    result = {}
    for identity, reference in rows:
        loaded = handoff.load(store, artifact_dir, **reference)
        try:
            result[identity] = training.project(loaded)
        except training.ProjectionUnavailable as error:
            result[identity] = str(error)
    return result


def native_run(value, config, expected_method_digest):
    if training.method()["digest"] != files.checksum(expected_method_digest):
        training.fail("METHOD_CHANGED")
    baseline = native.run(value, config)
    with PrivateContentStore(config["material_store"]) as store:
        raw = store.get_object(config["reference_digest"])
        references = local.decode(raw, config["reference_digest"])
        projected = projections(
            store,
            config["artifact_dir"],
            [(r["admission_id"], r["reference"]) for r in references["rows"]],
        )
    candidate = training.train(
        value["training_export"],
        projected,
        expected_method_digest=expected_method_digest,
        source_digest=config["reference_digest"],
    )
    return baseline | {"complete_feature_training": candidate}


def assemble(
    store,
    artifact_dir,
    selection_raw,
    labels_raw,
    *,
    expected_feature_training_method_digest,
    **expected,
):
    if training.method()["digest"] != files.checksum(expected_feature_training_method_digest):
        training.fail("METHOD_CHANGED")
    baseline = local.assemble(store, artifact_dir, selection_raw, labels_raw, **expected)
    selection = local.decode(selection_raw, expected["expected_selection_digest"])
    labels = local.decode(labels_raw, expected["expected_labels_digest"])
    members = {r["id"]: r for r in selection["members"] if r["purpose"] != "final_test"}
    # The existing assembly validates every final-side material identity but no
    # final labels; final features are not supplied to fit/selection/calibration.
    projected = projections(
        store, artifact_dir, [(key, m["reference"]) for key, m in members.items()]
    )
    rows = [
        {
            key: members[r["id"]][key]
            for key in ("id", "project_id", "group_id", "purpose", "submitted_at")
        }
        | r
        for r in labels["rows"]
    ]
    bundle = {
        "schema": "package-history-training-export/1",
        "origin": "synthetic",
        "cohort_id": selection["cohort_id"],
        "protocol": cpu.protocol(),
        "timing": selection["timing"],
        "rows": rows,
        "membership_digest": expected["expected_selection_digest"],
    }
    candidate = training.train(
        bundle,
        projected,
        expected_method_digest=expected_feature_training_method_digest,
        source_digest=expected["expected_selection_digest"],
    )
    return baseline | {"complete_feature_training": candidate}


def freeze(store, artifact_dir, result_dir, selection_raw, labels_raw, *, command_id, **expected):
    files.command(command_id)
    result = assemble(store, artifact_dir, selection_raw, labels_raw, **expected)
    result_raw = canonical(result)
    for raw in (selection_raw, labels_raw, result_raw):
        key = store.put_object(raw)
        if store.get_object(key) != raw:
            training.fail("CONTENT_CHANGED")
    record = canonical(
        {
            "version": training.VERSION,
            "command_id": command_id,
            "result_digest": sha(result_raw),
            "candidate_status": result["complete_feature_training"]["status"],
            **expected,
        }
    )
    replayed = handoff._index(result_dir, record, command_id)
    return receipt(record, replayed)


def receipt(raw, replayed):
    record = files.decode(raw)
    return {
        "version": training.VERSION,
        "command_id": record["command_id"],
        "artifact_digest": sha(raw),
        "result_digest": record["result_digest"],
        "feature_candidate_status": record["candidate_status"],
        "replayed": replayed,
        "formal_prediction": None,
        "provider_requests": 0,
        "paid_calls": 0,
        **handoff.FLAGS,
    }


def reopen(
    store,
    artifact_dir,
    result_dir,
    *,
    command_id,
    expected_artifact_digest,
    expected_feature_training_method_digest,
):
    fd = files.directory(result_dir)
    try:
        raw = files.private_read(
            files.command(command_id) + ".json", directory_fd=fd, maximum=local.MAX_BYTES
        )
    finally:
        os.close(fd)
    record = local.decode(raw, expected_artifact_digest)
    local.exact(
        record,
        {
            "version",
            "command_id",
            "result_digest",
            "candidate_status",
            "expected_selection_digest",
            "expected_labels_digest",
            "expected_calibration_method_digest",
            "expected_feature_training_method_digest",
        },
    )
    if (
        record["version"] != training.VERSION
        or record["command_id"] != command_id
        or record["expected_feature_training_method_digest"]
        != expected_feature_training_method_digest
    ):
        training.fail("RECORD_CHANGED")
    expected = {k: v for k, v in record.items() if k.startswith("expected_")}
    result = assemble(
        store,
        artifact_dir,
        store.get_object(record["expected_selection_digest"]),
        store.get_object(record["expected_labels_digest"]),
        **expected,
    )
    result_raw = canonical(result)
    if (
        result["complete_feature_training"]["status"] != record["candidate_status"]
        or sha(result_raw) != record["result_digest"]
        or store.get_object(sha(result_raw)) != result_raw
    ):
        training.fail("RESULT_CHANGED")
    return receipt(raw, True)
