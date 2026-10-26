"""Private immutable /2 feature handoff; no DB, provider, labels or training authority.

This local research artifact does not replace native input/execution registration.
Consumers must supply independently retained expected identities on every read.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from uuid import UUID, uuid4

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_features as features
from packages.model_governance.common import GovernanceError

VERSION = "package-history-feature-handoff/1"
MAX_BYTES = 2 * features.MAX_BYTES
ORIGINS = {"synthetic_mechanism", "unqualified_research"}


def fail(code):
    raise GovernanceError(
        "PACKAGE_FEATURE_HANDOFF_" + code, "Private frozen research handoff rejected"
    )


def checksum(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) or value == "0" * 64:
        fail("EXPECTED_IDENTITY_REQUIRED")
    return value


def command(value):
    try:
        if str(UUID(value)) != value:
            fail("COMMAND_INVALID")
    except (ValueError, TypeError, AttributeError):
        fail("COMMAND_INVALID")
    return value


def method_digest():
    return digest(
        {
            "version": VERSION,
            "source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "features": features.descriptor(),
        }
    )


def decode(raw):
    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                fail("JSON_INVALID")
            value[key] = child
        return value

    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
            fail("SIZE_INVALID")
        value = json.loads(raw, object_pairs_hook=pairs)
        canonical(value)  # Reject floats, unsafe integers and noncanonical value types.
        return value
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        fail("JSON_INVALID")


def private_read(path, *, directory_fd=None, maximum=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or not 0 < info.st_size <= maximum
        ):
            fail("PRIVATE_FILE_REQUIRED")
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(maximum + 1)
        after = os.fstat(fd)
        # The publisher unlinks its temporary name after creating the final
        # hard link. That 2 -> 1 link cleanup changes ctime without changing bytes.
        # Every caller still compares the bytes with its independent identity.
        link_cleanup = info.st_nlink == 2 and after.st_nlink == 1
        if (
            len(data) != info.st_size
            or (info.st_size, info.st_mtime_ns, info.st_uid, info.st_mode)
            != (after.st_size, after.st_mtime_ns, after.st_uid, after.st_mode)
            or (info.st_ctime_ns != after.st_ctime_ns and not link_cleanup)
        ):
            fail("FILE_CHANGED")
        return data
    finally:
        os.close(fd)


def directory(path):
    # The selected directory must already exist. Never change its access policy.
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        fail("PRIVATE_DIRECTORY_REQUIRED")
    return fd


def prepare(
    projection,
    *,
    command_id,
    origin,
    expected_projection_digest,
    expected_binding_digest,
    expected_feature_method_digest,
    expected_handoff_method_digest,
):
    command(command_id)
    if origin not in ORIGINS:
        fail("ORIGIN_REQUIRED")
    for value in (
        expected_projection_digest,
        expected_binding_digest,
        expected_feature_method_digest,
        expected_handoff_method_digest,
    ):
        checksum(value)
    if method_digest() != expected_handoff_method_digest:
        fail("METHOD_CHANGED")
    # Own the input copy before validating/deriving anything retained on disk.
    projection = decode(canonical(projection))
    if (
        not isinstance(projection, dict)
        or digest(projection.get("binding")) != expected_binding_digest
    ):
        fail("BINDING_MISMATCH")
    result = features.build_features(
        projection,
        expected_projection_digest=expected_projection_digest,
        expected_method_digest=expected_feature_method_digest,
    )
    if method_digest() != expected_handoff_method_digest:
        fail("METHOD_CHANGED")
    if result["feature_coverage"] != "complete":
        fail("FEATURES_INCOMPLETE")
    value = {
        "version": VERSION,
        "command_id": command_id,
        "origin": origin,
        "purpose": "research_feature_handoff_only",
        "projection_digest": expected_projection_digest,
        "binding_digest": expected_binding_digest,
        "feature_method_digest": expected_feature_method_digest,
        "handoff_method_digest": expected_handoff_method_digest,
        "projection": projection,
        "result": result,
        "training_eligible": False,
        "metrics_eligible": False,
        "formal_prediction_eligible": False,
        "provider_requests": 0,
        "paid_calls": 0,
    }
    raw = canonical(value)
    if len(raw) > MAX_BYTES:
        fail("SIZE_INVALID")
    return raw


def receipt(raw, *, replayed):
    value = decode(raw)
    result = value["result"]
    return {
        "version": VERSION,
        "command_id": value["command_id"],
        "artifact_digest": hashlib.sha256(raw).hexdigest(),
        "projection_digest": value["projection_digest"],
        "binding_digest": value["binding_digest"],
        "feature_method_digest": value["feature_method_digest"],
        "handoff_method_digest": value["handoff_method_digest"],
        "origin": value["origin"],
        "feature_coverage": result["feature_coverage"],
        "expected_rule_count": result["expected_rule_count"],
        "complete_rule_count": result["complete_rule_count"],
        "replayed": replayed,
        "research_only": True,
        "training_eligible": False,
        "metrics_eligible": False,
        "formal_prediction": None,
        "provider_requests": 0,
        "paid_calls": 0,
    }


def freeze(path, projection, **expected):
    raw = prepare(projection, **expected)
    name = command(expected["command_id"]) + ".json"
    directory_fd = directory(path)
    temporary = ".pending-" + uuid4().hex
    try:
        try:
            existing = private_read(name, directory_fd=directory_fd)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing != raw:
                fail("COMMAND_CONFLICT")
            os.fsync(directory_fd)
            return receipt(raw, replayed=True)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as target:
                target.write(raw)
                target.flush()
                os.fsync(fd)
            try:
                # Atomic publication without overwriting a concurrent winner.
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                replayed = False
            except FileExistsError:
                if private_read(name, directory_fd=directory_fd) != raw:
                    fail("COMMAND_CONFLICT")
                replayed = True
            os.fsync(directory_fd)
        finally:
            os.close(fd)
            os.unlink(temporary, dir_fd=directory_fd)
        return receipt(raw, replayed=replayed)
    finally:
        os.close(directory_fd)


def _verified_bytes(path, *, expected_artifact_digest, **expected):
    checksum(expected_artifact_digest)
    directory_fd = directory(path)
    try:
        raw = private_read(command(expected["command_id"]) + ".json", directory_fd=directory_fd)
    finally:
        os.close(directory_fd)
    if hashlib.sha256(raw).hexdigest() != expected_artifact_digest:
        fail("ARTIFACT_MISMATCH")
    value = decode(raw)
    if not isinstance(value, dict) or "projection" not in value:
        fail("ARTIFACT_INVALID")
    rebuilt = prepare(value["projection"], **expected)
    if raw != rebuilt:
        fail("ARTIFACT_MISMATCH")
    return raw


def load(path, *, expected_artifact_digest, **expected):
    """Return an owned copy for research consumers; no training eligibility is inferred."""
    return decode(
        _verified_bytes(path, expected_artifact_digest=expected_artifact_digest, **expected)
    )


def reopen(path, *, expected_artifact_digest, **expected):
    """Metadata-only acknowledgement safe for command-line output."""
    return receipt(
        _verified_bytes(path, expected_artifact_digest=expected_artifact_digest, **expected),
        replayed=True,
    )
