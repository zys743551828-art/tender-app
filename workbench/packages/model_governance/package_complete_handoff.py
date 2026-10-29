"""Persist existing /3 material and judgments using the existing private CAS.

Only the transport envelope is new. No native freshness, model or training grant.
"""

import os
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from packages.domain.providers.deepseek_vision import VisionGeneration, parse_response
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_features as features
from packages.model_governance import package_current_material as current
from packages.model_governance import package_feature_handoff as local
from packages.model_governance import package_material_archive as archive
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import MAX_COMMIT_BYTES, PrivateContentStore, sha

VERSION = "package-history-feature-handoff/2"
SOURCE_VERSION = "package-history-feature-source/2"
MAX_ATTEMPTS = 120
MAX_TOTAL_BYTES = 192 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 96 * 1024 * 1024
FLAGS = {
    "native_binding_verified": False,
    "current_native_facts_rechecked": False,
    "input_authority_granted": False,
    "execution_authorized": False,
    "training_eligible": False,
    "metrics_eligible": False,
    "formal_prediction_eligible": False,
}


def fail(code):
    local.fail("COMPLETE_" + code)


def method_digest():
    return digest(
        {
            "version": VERSION,
            "source": sha(Path(__file__).read_bytes()),
            "archive_method": archive.method_digest(),
            "input_method": material.method_digest(),
            "serializer_method": vision.serializer_digest(),
            "feature_method": features.method_digest(),
            "private_index_method": local.method_digest(),
            "limits": [MAX_ATTEMPTS, MAX_TOTAL_BYTES, MAX_RESPONSE_BYTES, MAX_REQUEST_BYTES],
        }
    )


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        fail("FIELDS_INVALID")


def _summaries(bundle, attempts, expected_input_digest, expected_feature_method_digest):
    if type(attempts) is not list or not 1 <= len(attempts) <= MAX_ATTEMPTS:
        fail("ATTEMPT_LIMIT")
    rules = [r["rule_id"] for r in bundle.context.metadata["rules"] if r["selection"] == "include"]
    if not rules or any(
        type(a) is not features.CompleteJudgmentAttempt or a.rule_id not in rules for a in attempts
    ):
        fail("RULE_SET_INVALID")
    if len(rules) * 3 > len(attempts) or {a.rule_id for a in attempts} != set(rules):
        fail("FEATURES_INCOMPLETE")
    calls, responses = set(), set()
    for row in attempts:
        if row.call_id in calls:
            fail("CALL_REUSED")
        calls.add(row.call_id)
        if row.generation is not None:
            if row.generation.response_id in responses:
                fail("RESPONSE_REUSED")
            responses.add(row.generation.response_id)
    result = [
        features.aggregate_rule(
            bundle,
            rule,
            [a for a in attempts if a.rule_id == rule],
            expected_input_digest=expected_input_digest,
            expected_method_digest=expected_feature_method_digest,
        )
        for rule in rules
    ]
    if any(r["feature_coverage"] != "complete" for r in result):
        fail("FEATURES_INCOMPLETE")
    return result


def prepare_source(
    bundle,
    attempts,
    *,
    expected_input_digest,
    expected_binding_digest,
    expected_feature_method_digest,
    expected_handoff_method_digest,
):
    for value in (
        expected_input_digest,
        expected_binding_digest,
        expected_feature_method_digest,
        expected_handoff_method_digest,
    ):
        local.checksum(value)
    if method_digest() != expected_handoff_method_digest:
        fail("METHOD_CHANGED")
    checked = material.verify_input(bundle, expected_input_digest)
    if checked.metadata["binding_reference_digest"] != expected_binding_digest:
        fail("BINDING_MISMATCH")
    if type(attempts) is not list or not 1 <= len(attempts) <= MAX_ATTEMPTS:
        fail("ATTEMPT_LIMIT")
    # Frozen dataclasses still contain mutable receipts and parsed JSON. Own one
    # snapshot before validation so a caller cannot change it before persistence.
    attempts = deepcopy(attempts)
    raw_total = 0
    request_sizes = {}
    for row in attempts:
        if (
            type(row) is not features.CompleteJudgmentAttempt
            or type(row.request) is not vision.PreparedCompleteVisionRequest
        ):
            fail("ATTEMPT_INVALID")
        if (
            type(row.request.body) is not bytes
            or not 0 < len(row.request.body) <= vision.MAX_BODY_BYTES
        ):
            fail("REQUEST_LIMIT")
        request_sizes[sha(row.request.body)] = len(row.request.body)
        if sum(request_sizes.values()) > MAX_REQUEST_BYTES:
            fail("REQUEST_LIMIT")
        if row.generation is not None:
            if (
                type(row.generation) is not VisionGeneration
                or type(row.generation.raw_response) is not bytes
                or not 0 < len(row.generation.raw_response) <= 1024 * 1024
            ):
                fail("RESPONSE_LIMIT")
            raw_total += len(row.generation.raw_response)
            if raw_total > MAX_RESPONSE_BYTES:
                fail("RESPONSE_LIMIT")
            replay = parse_response(
                row.generation.raw_response,
                row.generation.request_id,
                row.request.receipt["request_digest"],
            )
            if canonical(
                {k: v for k, v in asdict(replay).items() if k != "raw_response"}
            ) != canonical(
                {k: v for k, v in asdict(row.generation).items() if k != "raw_response"}
            ):
                fail("GENERATION_MISMATCH")
    summaries = _summaries(checked, attempts, expected_input_digest, expected_feature_method_digest)
    prepared = archive.prepare(
        checked.context, expected_context_digest=checked.metadata["context_digest"]
    )
    objects = dict(prepared.objects)

    def put(raw, limit):
        if type(raw) is not bytes or not 0 < len(raw) <= limit:
            fail("OBJECT_LIMIT")
        key = sha(raw)
        objects[key] = raw
        if sum(map(len, objects.values())) > MAX_TOTAL_BYTES:
            fail("TOTAL_LIMIT")
        return {"sha256": key, "byte_size": len(raw)}

    observation = put(canonical(checked.context.origin.metadata), 2 * 1024 * 1024)
    input_metadata = put(canonical(checked.metadata), MAX_COMMIT_BYTES)
    originals = [
        {"document_version_id": key, "object": put(raw, 32 * 1024 * 1024)}
        for key, raw in sorted(checked.context.origin.originals.items())
    ]
    records, requests, response_bytes = [], {}, 0
    for row in attempts:
        request = put(row.request.body, vision.MAX_BODY_BYTES)
        requests[request["sha256"]] = request["byte_size"]
        if sum(requests.values()) > MAX_REQUEST_BYTES:
            fail("REQUEST_LIMIT")
        generation = None
        if row.generation is not None:
            raw = row.generation.raw_response
            response_bytes += len(raw)
            if response_bytes > MAX_RESPONSE_BYTES:
                fail("RESPONSE_LIMIT")
            meta = {k: v for k, v in asdict(row.generation).items() if k != "raw_response"}
            generation = {
                "raw_response": put(raw, 1024 * 1024),
                "metadata": put(canonical(meta), 2 * 1024 * 1024),
            }
        records.append(
            {
                "rule_id": row.rule_id,
                "slot": row.slot,
                "attempt": row.attempt,
                "call_id": row.call_id,
                "state": row.state,
                "request_body": request,
                "request_receipt": put(canonical(row.request.receipt), MAX_COMMIT_BYTES),
                "generation": generation,
            }
        )
    packet = {
        "version": SOURCE_VERSION,
        "method_digest": expected_handoff_method_digest,
        "input_digest": expected_input_digest,
        "binding_digest": expected_binding_digest,
        "feature_method_digest": expected_feature_method_digest,
        "material_archive": prepared.manifest,
        "observation": observation,
        "input_metadata": input_metadata,
        "originals": originals,
        "attempts": records,
        **FLAGS,
    }
    raw = canonical(packet)
    if len(raw) > MAX_COMMIT_BYTES or method_digest() != expected_handoff_method_digest:
        fail("SOURCE_LIMIT_OR_METHOD_CHANGED")
    return raw, objects, summaries


def save_source(store: PrivateContentStore, bundle, attempts, **expected):
    raw, objects, _ = prepare_source(bundle, attempts, **expected)
    for key, value in objects.items():
        if store.put_object(value) != key or store.get_object(key) != value:
            fail("CONTENT_MISMATCH")
    # Source commit is a byte-identity record, never a native execution receipt.
    return store.publish(raw)


@dataclass(frozen=True, repr=False)
class CompleteResearchInput:
    bundle: material.MaterialInput
    attempts: list[features.CompleteJudgmentAttempt]
    features: list[dict]


def load_source(store: PrivateContentStore, source_commit, **expected):
    raw = store.get_commit(source_commit)
    packet = archive._decode(raw)
    exact(
        packet,
        {
            "version",
            "method_digest",
            "input_digest",
            "binding_digest",
            "feature_method_digest",
            "material_archive",
            "observation",
            "input_metadata",
            "originals",
            "attempts",
            *FLAGS,
        },
    )
    if (
        packet["version"] != SOURCE_VERSION
        or packet["method_digest"] != expected["expected_handoff_method_digest"]
        or packet["input_digest"] != expected["expected_input_digest"]
        or packet["binding_digest"] != expected["expected_binding_digest"]
        or packet["feature_method_digest"] != expected["expected_feature_method_digest"]
        or any(packet[k] is not False for k in FLAGS)
    ):
        fail("SOURCE_IDENTITY_MISMATCH")
    if method_digest() != expected["expected_handoff_method_digest"]:
        fail("METHOD_CHANGED")
    if (
        type(packet["attempts"]) is not list
        or not 1 <= len(packet["attempts"]) <= MAX_ATTEMPTS
        or type(packet["originals"]) is not list
        or not 1 <= len(packet["originals"]) <= 32
    ):
        fail("SOURCE_LIMIT")
    cache: dict[str, bytes] = {}

    def get(ref, limit):
        exact(ref, {"sha256", "byte_size"})
        local.checksum(ref["sha256"])
        if type(ref["byte_size"]) is not int or not 0 < ref["byte_size"] <= limit:
            fail("OBJECT_LIMIT")
        if ref["sha256"] not in cache:
            if sum(map(len, cache.values())) + ref["byte_size"] > MAX_TOTAL_BYTES:
                fail("TOTAL_LIMIT")
            cache[ref["sha256"]] = store.get_object(ref["sha256"])
        value = cache[ref["sha256"]]
        if len(value) != ref["byte_size"]:
            fail("CONTENT_MISMATCH")
        return value

    # Existing archive reader verifies its unchanged /1 envelope and /3 context.
    archived = archive._load_objects(
        store, packet["material_archive"], packet["material_archive"]["context_digest"]
    )
    cache.update({sha(blob): blob for blob in archived.image_blobs.values()})
    context_meta = archived.context_metadata
    cache[sha(canonical(context_meta))] = canonical(context_meta)
    observation = archive._decode(get(packet["observation"], 2 * 1024 * 1024))
    input_meta = archive._decode(get(packet["input_metadata"], MAX_COMMIT_BYTES))
    originals = {}
    for row in packet["originals"]:
        exact(row, {"document_version_id", "object"})
        key = row["document_version_id"]
        if type(key) is not str or key in originals:
            fail("ORIGINAL_SET_INVALID")
        originals[key] = get(row["object"], 32 * 1024 * 1024)
    bundles = {}
    for doc, manifest in context_meta["material"]["page_asset_manifests"].items():
        ids = [
            row["asset"]["id"]
            for row in context_meta["images"]
            if row["document_version_id"] == doc
        ]
        bundles[doc] = assets.PageAssetBundle(
            manifest, {key: archived.image_blobs[key] for key in ids}
        )
    origin = current.CurrentMaterial(observation, context_meta["material"], originals, bundles)
    bundle = material.MaterialInput(input_meta, material.MaterialContext(context_meta, origin))
    attempts = []
    response_bytes, requests = 0, {}
    for row in packet["attempts"]:
        exact(
            row,
            {
                "rule_id",
                "slot",
                "attempt",
                "call_id",
                "state",
                "request_body",
                "request_receipt",
                "generation",
            },
        )
        body = get(row["request_body"], vision.MAX_BODY_BYTES)
        requests[sha(body)] = len(body)
        if sum(requests.values()) > MAX_REQUEST_BYTES:
            fail("REQUEST_LIMIT")
        request = vision.PreparedCompleteVisionRequest(
            body, archive._decode(get(row["request_receipt"], MAX_COMMIT_BYTES))
        )
        generation = None
        if row["generation"] is not None:
            entry = row["generation"]
            exact(entry, {"raw_response", "metadata"})
            response = get(entry["raw_response"], 1024 * 1024)
            response_bytes += len(response)
            if response_bytes > MAX_RESPONSE_BYTES:
                fail("RESPONSE_LIMIT")
            meta = archive._decode(get(entry["metadata"], 2 * 1024 * 1024))
            generation = parse_response(
                response, meta["request_id"], request.receipt["request_digest"]
            )
            if canonical(
                {k: v for k, v in asdict(generation).items() if k != "raw_response"}
            ) != canonical(meta):
                fail("GENERATION_MISMATCH")
        attempts.append(
            features.CompleteJudgmentAttempt(
                row["rule_id"],
                row["slot"],
                row["attempt"],
                row["call_id"],
                row["state"],
                request,
                generation,
            )
        )
    rebuilt, objects, summaries = prepare_source(bundle, attempts, **expected)
    if rebuilt != raw or any(store.get_object(key) != value for key, value in objects.items()):
        fail("SOURCE_MISMATCH")
    return CompleteResearchInput(
        material.verify_input(bundle, expected["expected_input_digest"]), attempts, summaries
    )


def _index(path, raw, command_id):
    """Use the existing private boundary; serialize publication without new grants."""
    import fcntl

    fd = local.directory(path)
    name = local.command(command_id) + ".json"
    temporary = ".pending-" + uuid4().hex
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    fail("BUSY")
                time.sleep(0.01)
        try:
            old = local.private_read(name, directory_fd=fd, maximum=MAX_COMMIT_BYTES)
        except FileNotFoundError:
            old = None
        if old is not None:
            if old != raw:
                fail("COMMAND_CONFLICT")
            os.fsync(fd)
            return True
        stream = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        try:
            with os.fdopen(stream, "wb", closefd=False) as target:
                target.write(raw)
                target.flush()
                os.fsync(stream)
            os.rename(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(stream)
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
        return False
    finally:
        os.close(fd)


def _record(store, source_commit, command_id, origin, expected):
    local.command(command_id)
    if origin not in local.ORIGINS:
        fail("ORIGIN_REQUIRED")
    loaded = load_source(store, source_commit, **expected)
    feature_raw = canonical({"items": loaded.features, **FLAGS})
    if len(feature_raw) > 8 * 1024 * 1024:
        fail("FEATURE_LIMIT")
    value = {
        "version": VERSION,
        "command_id": command_id,
        "origin": origin,
        "source_commit": source_commit,
        "input_digest": expected["expected_input_digest"],
        "binding_digest": expected["expected_binding_digest"],
        "feature_method_digest": expected["expected_feature_method_digest"],
        "handoff_method_digest": expected["expected_handoff_method_digest"],
        "features_object": {"sha256": sha(feature_raw), "byte_size": len(feature_raw)},
        "rule_count": len(loaded.features),
        **FLAGS,
    }
    return canonical(value), feature_raw, loaded


def _receipt(raw, replayed):
    value = archive._decode(raw)
    return {k: v for k, v in value.items() if k != "features_object"} | {
        "artifact_digest": sha(raw),
        "replayed": replayed,
        "formal_prediction": None,
        "provider_requests": 0,
        "paid_calls": 0,
    }


def freeze(store, path, *, source_commit, command_id, origin, **expected):
    raw, feature_raw, _ = _record(store, source_commit, command_id, origin, expected)
    key = store.put_object(feature_raw)
    if store.get_object(key) != feature_raw:
        fail("CONTENT_MISMATCH")
    replayed = _index(path, raw, command_id)
    return _receipt(raw, replayed)


def load(store, path, *, source_commit, command_id, origin, expected_artifact_digest, **expected):
    fd = local.directory(path)
    try:
        raw = local.private_read(
            local.command(command_id) + ".json", directory_fd=fd, maximum=MAX_COMMIT_BYTES
        )
    finally:
        os.close(fd)
    if sha(raw) != local.checksum(expected_artifact_digest):
        fail("ARTIFACT_MISMATCH")
    rebuilt, feature_raw, loaded = _record(store, source_commit, command_id, origin, expected)
    if rebuilt != raw or store.get_object(sha(feature_raw)) != feature_raw:
        fail("ARTIFACT_MISMATCH")
    return loaded


def reopen(store, path, **expected):
    loaded = load(store, path, **expected)
    return {
        "version": VERSION,
        "command_id": expected["command_id"],
        "artifact_digest": expected["expected_artifact_digest"],
        "source_commit": expected["source_commit"],
        "input_digest": expected["expected_input_digest"],
        "rule_count": len(loaded.features),
        "replayed": True,
        "formal_prediction": None,
        "provider_requests": 0,
        "paid_calls": 0,
        **FLAGS,
    }
