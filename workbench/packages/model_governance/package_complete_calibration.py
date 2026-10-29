"""Pinned /3 selection and separated labels for synthetic baseline assembly only.

No native admission is inferred from a caller's manifest or content hash. The
existing historical constant-baseline engine is reused without legacy vectors.
"""

from pathlib import Path

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_handoff as local
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import instant
from packages.storage.private_cas import sha

VERSION = "package-complete-calibration-assembly/1"
MAX_BYTES = 256 * 1024
MAX_MEMBERS = 64
REFERENCE = {
    "source_commit",
    "command_id",
    "origin",
    "expected_artifact_digest",
    "expected_input_digest",
    "expected_binding_digest",
    "expected_feature_method_digest",
    "expected_handoff_method_digest",
}


def fail(code):
    local.fail("CALIBRATION_" + code)


def exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        fail("FIELDS_INVALID")


def method_digest():
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "handoff": handoff.method_digest(),
            "cpu": cpu.method(),
            "protocol": cpu.wire(cpu.protocol()),
            "limits": [MAX_BYTES, MAX_MEMBERS],
        }
    )


def decode(raw, expected):
    if len(raw) > MAX_BYTES or sha(raw) != local.checksum(expected):
        fail("PIN_MISMATCH")
    return local.decode(raw)


def assemble(
    store,
    artifact_dir,
    selection_raw,
    labels_raw,
    *,
    expected_selection_digest,
    expected_labels_digest,
    expected_calibration_method_digest,
):
    if method_digest() != local.checksum(expected_calibration_method_digest):
        fail("METHOD_CHANGED")
    selection = decode(selection_raw, expected_selection_digest)
    exact(selection, {"version", "origin", "cohort_id", "method_digest", "timing", "members"})
    if (
        selection["version"] != VERSION
        or selection["origin"] != "synthetic_mechanism"
        or selection["method_digest"] != expected_calibration_method_digest
    ):
        fail("SYNTHETIC_ONLY")
    local.command(selection["cohort_id"])
    timing = selection["timing"]
    exact(timing, {"submission_split_at", "label_available_as_of", "training_frozen_at"})
    boundary, cutoff, frozen = (
        instant(timing[k])
        for k in ("submission_split_at", "label_available_as_of", "training_frozen_at")
    )
    if boundary > frozen or cutoff > frozen:
        fail("TIMING_INVALID")
    members = selection["members"]
    if type(members) is not list or not 1 <= len(members) <= MAX_MEMBERS:
        fail("MEMBERS_INVALID")
    seen: set[str] = set()
    sources: set[str] = set()
    inputs: set[str] = set()
    scopes: set[str] = set()
    partitions: dict[tuple[str, str], str] = {}
    verified = []
    calls, responses = set(), set()
    for member in members:
        exact(
            member,
            {
                "id",
                "project_id",
                "group_id",
                "purpose",
                "submitted_at",
                "scope_id",
                "scope_digest",
                "reference",
            },
        )
        for field in ("id", "project_id", "group_id", "scope_id"):
            local.command(member[field])
        local.checksum(member["scope_digest"])
        purpose = member["purpose"]
        if purpose not in {"fit", "development", "calibration", "final_test"}:
            fail("PURPOSE_INVALID")
        if (instant(member["submitted_at"]) < boundary) != (purpose != "final_test"):
            fail("SPLIT_INVALID")
        reference = member["reference"]
        exact(reference, REFERENCE)
        if reference["origin"] != "synthetic_mechanism":
            fail("SYNTHETIC_ONLY")
        for values, key in (
            (seen, member["id"]),
            (sources, reference["source_commit"]),
            (inputs, reference["expected_input_digest"]),
            (scopes, member["scope_id"]),
        ):
            if key in values:
                fail("REPEATED_SAMPLE")
            values.add(key)
        # A project cannot evade separation by being assigned a different group.
        for field in ("project_id", "group_id"):
            key = (field, member[field])
            if partitions.setdefault(key, purpose) != purpose:
                fail("PARTITION_LEAK")
        loaded = handoff.load(store, artifact_dir, **reference)
        for attempt in loaded.attempts:
            if attempt.call_id in calls:
                fail("CALL_REUSED")
            calls.add(attempt.call_id)
            if attempt.generation is not None:
                response_id = attempt.generation.response_id
                if response_id in responses:
                    fail("RESPONSE_REUSED")
                responses.add(response_id)
        context = loaded.bundle.context.metadata
        if any(
            context[key] != member[field]
            for key, field in (
                ("bid_id", "project_id"),
                ("scope_id", "scope_id"),
                ("scope_digest", "scope_digest"),
            )
        ):
            fail("SOURCE_SCOPE_MISMATCH")
        if instant(context["input_as_of"]) > instant(member["submitted_at"]):
            fail("POST_SUBMISSION_INPUT")
        verified.append(
            {
                "id": member["id"],
                "feature_digest": digest(loaded.features),
                "input_digest": reference["expected_input_digest"],
            }
        )
    # Only after all label-free /3 consumers finish may the separate label object
    # be decoded. No label object is passed to material/request/feature builders.
    labels = decode(labels_raw, expected_labels_digest)
    exact(labels, {"version", "selection_digest", "origin", "rows"})
    if (
        labels["version"] != VERSION
        or labels["origin"] != "synthetic_mechanism"
        or labels["selection_digest"] != expected_selection_digest
    ):
        fail("LABEL_BINDING_INVALID")
    rows = labels["rows"]
    train = {m["id"]: m for m in members if m["purpose"] != "final_test"}
    if type(rows) is not list or len(rows) != len(train):
        fail("LABEL_DENOMINATOR")
    consumed, cpu_rows = set(), []
    for row in rows:
        exact(row, {"id", "target", "label_known_at"})
        if row["id"] not in train or row["id"] in consumed:
            fail("LABEL_DENOMINATOR")
        consumed.add(row["id"])
        member = train[row["id"]]
        cpu_rows.append(
            {
                key: member[key]
                for key in ("id", "project_id", "group_id", "purpose", "submitted_at")
            }
            | row
        )
    result = cpu.train(
        {
            "schema": "package-history-training-export/1",
            "origin": "synthetic",
            "cohort_id": selection["cohort_id"],
            "protocol": cpu.protocol(),
            "timing": timing,
            "rows": cpu_rows,
            "membership_digest": expected_selection_digest,
        }
    )
    return {
        "version": VERSION,
        "origin": "synthetic_mechanism",
        "method_digest": expected_calibration_method_digest,
        "selection_digest": expected_selection_digest,
        "labels_digest": expected_labels_digest,
        "verified_features": verified,
        "mechanism_baseline_result": result,
        "features_used_for_fit": False,
        "formal_prediction": None,
        "acceptance_decision": "unavailable",
        "provider_requests": 0,
        "paid_calls": 0,
        **handoff.FLAGS,
    }


def freeze(store, artifact_dir, result_dir, selection_raw, labels_raw, *, command_id, **expected):
    local.command(command_id)
    result = assemble(store, artifact_dir, selection_raw, labels_raw, **expected)
    result_raw = canonical(result)
    for raw in (selection_raw, labels_raw, result_raw):
        key = store.put_object(raw)
        if store.get_object(key) != raw:
            fail("CONTENT_CHANGED")
    record = canonical(
        {"version": VERSION, "command_id": command_id, "result_digest": sha(result_raw), **expected}
    )
    replayed = handoff._index(result_dir, record, command_id)
    return {
        "version": VERSION,
        "command_id": command_id,
        "artifact_digest": sha(record),
        "result_digest": sha(result_raw),
        "replayed": replayed,
        "formal_prediction": None,
        "provider_requests": 0,
        "paid_calls": 0,
        **handoff.FLAGS,
    }


def reopen(store, artifact_dir, result_dir, *, command_id, expected_artifact_digest):
    import os

    fd = local.directory(result_dir)
    try:
        raw = local.private_read(
            local.command(command_id) + ".json", directory_fd=fd, maximum=MAX_BYTES
        )
    finally:
        os.close(fd)
    record = decode(raw, expected_artifact_digest)
    exact(
        record,
        {
            "version",
            "command_id",
            "result_digest",
            "expected_selection_digest",
            "expected_labels_digest",
            "expected_calibration_method_digest",
        },
    )
    if record["version"] != VERSION or record["command_id"] != command_id:
        fail("RECORD_INVALID")
    expected = {k: record[k] for k in record if k.startswith("expected_")}
    result = assemble(
        store,
        artifact_dir,
        store.get_object(record["expected_selection_digest"]),
        store.get_object(record["expected_labels_digest"]),
        **expected,
    )
    result_raw = canonical(result)
    if (
        sha(result_raw) != record["result_digest"]
        or store.get_object(sha(result_raw)) != result_raw
    ):
        fail("RESULT_CHANGED")
    return {
        "version": VERSION,
        "command_id": command_id,
        "artifact_digest": sha(raw),
        "result_digest": sha(result_raw),
        "replayed": True,
        "formal_prediction": None,
        "provider_requests": 0,
        "paid_calls": 0,
        **handoff.FLAGS,
    }
