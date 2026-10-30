"""Bounded explicit codec and Linux tmpfs mailbox; no Docker or rendering."""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from packages.domain.errors import DomainError
from packages.word_intake import execution_transport as transport

LINUX = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux nofollow/dirfd/tmpfs contract"
)


def arguments(lane):
    common = {"profile": {"profile_digest": "frozen", "identity": {"protocol": "test-only"}}}
    if lane in {"external", "page"}:
        common["source"] = b"synthetic DOCX \x00\xff"
    if lane in {"page", "rich"}:
        common["snapshot"] = {"title": "中文 120", "sections": [{"content": []}]}
    if lane == "page":
        common["producer_manifest"] = {"source": "frozen"}
    if lane == "rich":
        common.update(
            {
                "mode": "continuous",
                "materials": [
                    {
                        "asset_id": "asset",
                        "asset_revision": 1,
                        "asset_version_id": "version",
                        "bytes": b"synthetic PNG\x00\xff",
                        "normalization_proof": {"output_digest": "proof"},
                    }
                ],
            }
        )
    return common


def result(*, rich=False):
    value = {
        "state": "succeeded",
        "coverage": "partial",
        "conversion_attempted": True,
        "error_code": None,
        "retryable": False,
        "gaps": ["SYNTHETIC_UNQUALIFIED"],
        "pdf": b"%PDF-synthetic\x00\xff",
        "chain": {"source_docx_digest": "frozen"},
        "measurements": {"page_count": 2, "bbox": [1.25, 2.5, 3.0, 4.0]},
    }
    if rich:
        value.update(
            {
                "docx": b"final DOCX\x00\xff",
                "producer_manifest": {"source": "final"},
                "render_iterations": [
                    {
                        "docx_bytes": b"first DOCX",
                        "pdf_bytes": b"%PDF-first",
                        "entries": [{"expected_start_page": None}],
                    },
                    {
                        "docx_bytes": b"final DOCX\x00\xff",
                        "pdf_bytes": value["pdf"],
                        "entries": [{"expected_start_page": 2}],
                    },
                ],
                "navigation_proof": {"fixed_point": True},
                "iteration_summaries": [{"gaps": ["INITIAL_UNKNOWN"]}],
            }
        )
    return value


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def rejected(code, function, *args, **kwargs):
    with pytest.raises(DomainError) as error:
        function(*args, **kwargs)
    assert error.value.code == code


@pytest.mark.parametrize("lane", ["external", "page", "rich"])
def test_complete_explicit_binary_round_trip(lane):
    supplied = arguments(lane)
    raw = transport._request(lane, supplied)
    request = transport.decode_request(raw)
    assert request["arguments"] == supplied
    assert len(request["request_id"]) == 32
    expected = result(rich=lane == "rich")
    encoded = transport.encode_response(raw, expected)
    assert transport.decode_response(raw, encoded) == expected
    assert supplied == arguments(lane) and expected == result(rich=lane == "rich")


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", "wrong"),
        ("request_id", "../outside"),
        ("lane", "shell"),
        ("unknown", True),
    ],
)
def test_request_envelope_is_closed(field, value):
    wire = json.loads(transport._request("external", arguments("external")))
    wire[field] = value
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_request, dump(wire))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"protocol":1,"protocol":2}',
        b'{"v":NaN}',
        b'{"v":Infinity}',
        b'{"v":1e999}',
        b"\xff",
        b"[[[",
    ],
)
def test_duplicate_keys_nonfinite_and_bad_json_rejected(raw):
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_request, raw)


@pytest.mark.parametrize(
    "attack", ["missing", "unknown", "bytes_elsewhere", "path", "bad_mode", "material_unknown"]
)
def test_arguments_have_only_lane_slots_and_never_coerce_objects(attack):
    lane = "rich" if attack in {"bad_mode", "material_unknown"} else "external"
    value = arguments(lane)
    if attack == "missing":
        value.pop("profile")
    elif attack == "unknown":
        value["command"] = "id"
    elif attack == "bytes_elsewhere":
        value["profile"]["blob"] = b"not an explicit slot"
    elif attack == "path":
        value["profile"]["path"] = Path("private")
    elif attack == "bad_mode":
        value["mode"] = {}
    else:
        value["materials"][0]["path"] = "private"
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport._request, lane, value)


@pytest.mark.parametrize("attack", ["digest", "size", "alphabet", "noncanonical", "unknown"])
def test_binary_slot_length_digest_and_canonical_base64_are_checked(attack):
    wire = json.loads(transport._request("external", {"source": b"a", "profile": {}}))
    slot = wire["arguments"]["source"]
    if attack == "digest":
        slot["sha256"] = "0" * 64
    elif attack == "size":
        slot["byte_size"] = 2
    elif attack == "alphabet":
        slot["base64"] = "!!!!"
    elif attack == "noncanonical":
        slot["base64"] = "YR=="  # decodes to a, but has nonzero padding bits
    else:
        slot["path"] = "ignored-is-not-allowed"
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_request, dump(wire))


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", "wrong"),
        ("request_id", "0" * 32),
        ("lane", "page"),
        ("request_sha256", "0" * 64),
    ],
)
def test_response_identity_and_exact_raw_request_binding(field, value):
    request = transport._request("external", arguments("external"))
    response = json.loads(transport.encode_response(request, result()))
    response[field] = value
    rejected("WORD_EXECUTION_RESPONSE_MISMATCH", transport.decode_response, request, dump(response))
    reformatted = json.dumps(json.loads(request), indent=2).encode()
    rejected(
        "WORD_EXECUTION_RESPONSE_MISMATCH",
        transport.decode_response,
        reformatted,
        transport.encode_response(request, result()),
    )


def test_error_response_never_becomes_conversion_success():
    request = transport._request("external", arguments("external"))
    raw = transport.encode_error(request, "WORD_CONVERSION_TIMEOUT")
    rejected("WORD_CONVERSION_TIMEOUT", transport.decode_response, request, raw)
    rejected(
        "WORD_EXECUTION_PROTOCOL_INVALID", transport.encode_error, request, "private detail /path"
    )
    response = json.loads(raw)
    response["result"] = json.loads(transport.encode_response(request, result()))["result"]
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_response, request, dump(response))


def test_response_unknown_fields_and_nonfinite_metadata_are_rejected():
    request = transport._request("external", arguments("external"))
    response = json.loads(transport.encode_response(request, result()))
    response["unknown"] = True
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_response, request, dump(response))
    del response["unknown"]
    response["result"]["chain"]["unknown"] = float("inf")
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_response, request, dump(response))


@pytest.mark.parametrize(
    "attack",
    [
        "unknown",
        "implicit_bytes",
        "iteration_unknown",
        "iteration_bytes_missing",
        "too_many_passes",
    ],
)
def test_result_cannot_drop_iteration_bytes_or_smuggle_other_slots(attack):
    value = result(rich=True)
    if attack == "unknown":
        value["arbitrary"] = "not allowed"
    elif attack == "implicit_bytes":
        value["chain"]["bytes"] = b"not a slot"
    elif attack == "iteration_unknown":
        value["render_iterations"][0]["path"] = "not allowed"
    elif attack == "iteration_bytes_missing":
        del value["render_iterations"][0]["docx_bytes"]
    else:
        value["render_iterations"] *= 2
    rejected(
        "WORD_EXECUTION_PROTOCOL_INVALID",
        transport.encode_response,
        transport._request("rich", arguments("rich")),
        value,
    )


def test_wire_individual_and_aggregate_binary_limits(monkeypatch):
    request = transport._request("rich", arguments("rich"))
    monkeypatch.setattr(transport, "MAX_REQUEST_BYTES", 10)
    rejected("WORD_EXECUTION_LIMIT", transport.decode_request, request)
    monkeypatch.setattr(transport, "MAX_REQUEST_BYTES", 160 * 1024 * 1024)
    monkeypatch.setattr(transport, "MAX_SOURCE_BYTES", 2)
    rejected("WORD_EXECUTION_LIMIT", transport._request, "external", arguments("external"))
    monkeypatch.setattr(transport, "MAX_SOURCE_BYTES", 100 * 1024 * 1024)
    monkeypatch.setattr(transport, "MAX_RESPONSE_BINARY_BYTES", len(result(rich=True)["pdf"]) + 1)
    rejected("WORD_EXECUTION_LIMIT", transport.encode_response, request, result(rich=True))
    monkeypatch.setattr(transport, "MAX_RESPONSE_BINARY_BYTES", 140 * 1024 * 1024)
    monkeypatch.setattr(transport, "MAX_RESPONSE_BYTES", 10)
    rejected("WORD_EXECUTION_LIMIT", transport.encode_response, request, result())


def test_nested_json_and_multiple_materials_have_total_bounds(monkeypatch):
    value = arguments("rich")
    value["materials"] *= 2
    monkeypatch.setattr(transport, "MAX_REQUEST_BINARY_BYTES", len(value["materials"][0]["bytes"]))
    rejected("WORD_EXECUTION_LIMIT", transport._request, "rich", value)
    deep = current = {}
    for _ in range(70):
        current["next"] = {}
        current = current["next"]
    rejected("WORD_EXECUTION_LIMIT", transport._plain, deep)


def test_default_native_and_invalid_configuration(monkeypatch):
    monkeypatch.delenv(transport.ENVIRONMENT_KEY, raising=False)
    assert transport.enabled() is False
    rejected("WORD_EXECUTION_NOT_CONFIGURED", transport.call, "external", **arguments("external"))
    for path in ["", "/tmp/other", "/tmp/word-execution/", "relative"]:
        monkeypatch.setenv(transport.ENVIRONMENT_KEY, path)
        rejected("WORD_EXECUTION_DIRECTORY_INVALID", transport.enabled)
    monkeypatch.setenv(transport.ENVIRONMENT_KEY, str(transport.DIRECTORY))
    monkeypatch.setattr(transport.sys, "platform", "win32")
    rejected("WORD_EXECUTION_DIRECTORY_INVALID", transport.enabled)


@pytest.fixture
def mailbox(monkeypatch, tmp_path):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux openat/nofollow/ownership/tmpfs contract")
    root = tmp_path / "mailbox"
    root.mkdir(mode=0o700)
    monkeypatch.setenv(transport.ENVIRONMENT_KEY, str(transport.DIRECTORY))

    def open_root():
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    monkeypatch.setattr(transport, "_open_directory", open_root)
    monkeypatch.setattr(transport, "MAX_RESPONSE_BYTES", 4096)
    return root


def host_once(root, *, attack=None):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        files = list(root.glob("*/request.json"))
        if files:
            request = files[0].read_bytes()
            job = files[0].parent
            if attack == "cancel":
                target = job / "cancel"
                target.write_bytes(b"")
                target.chmod(0o600)
                return
            response = transport.encode_response(
                request, result(rich=transport.decode_request(request)["lane"] == "rich")
            )
            if attack == "mismatch":
                value = json.loads(response)
                value["request_sha256"] = "0" * 64
                response = dump(value)
            temporary = job / ".response"
            temporary.write_bytes(response)
            temporary.chmod(0o600)
            temporary.rename(job / "response.json")
            return
        time.sleep(0.001)
    raise AssertionError("No request published")


@pytest.mark.parametrize("lane", ["external", "page", "rich"])
def test_mailbox_roundtrip_and_exact_success_cleanup(mailbox, lane):
    thread = threading.Thread(target=host_once, args=(mailbox,))
    thread.start()
    try:
        assert transport.call(lane, **arguments(lane)) == result(rich=lane == "rich")
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert list(mailbox.iterdir()) == [mailbox / ".client.lock"]


@pytest.mark.parametrize(
    "attack,code",
    [("mismatch", "WORD_EXECUTION_RESPONSE_MISMATCH"), ("cancel", "WORD_EXECUTION_CANCELLED")],
)
def test_bad_response_and_host_cancel_leave_revocation_marker(mailbox, attack, code):
    thread = threading.Thread(target=host_once, args=(mailbox,), kwargs={"attack": attack})
    thread.start()
    try:
        rejected(code, transport.call, "external", **arguments("external"))
    finally:
        thread.join(timeout=5)
    assert len(list(mailbox.glob("*/cancel"))) == 1


def test_timeout_never_accepts_late_response_or_claims_cleanup(mailbox, monkeypatch):
    monkeypatch.setitem(transport.TIMEOUTS, "external", 0.03)
    rejected("WORD_EXECUTION_TIMEOUT", transport.call, "external", **arguments("external"))
    job = next(mailbox.glob("*/cancel")).parent
    raw = (job / "request.json").read_bytes()
    response = transport.encode_response(raw, result())
    (job / "response.json").write_bytes(response)
    assert (job / "cancel").exists()
    # A new UUID request cannot consume the previous job's late response.
    rejected("WORD_EXECUTION_TIMEOUT", transport.call, "external", **arguments("external"))
    assert len(list(mailbox.glob("*/cancel"))) == 2


def test_keyboard_interrupt_revokes_without_claiming_executor_stopped(mailbox, monkeypatch):
    def interrupted(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(transport.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        transport.call("external", **arguments("external"))
    assert len(list(mailbox.glob("*/cancel"))) == 1
    assert len(list(mailbox.glob("*/request.json"))) == 1


def test_response_decoded_after_deadline_is_revoked(mailbox, monkeypatch):
    original_decode = transport.decode_response
    clock = time.monotonic
    expired = False

    def decode_then_expire(*args):
        nonlocal expired
        value = original_decode(*args)
        expired = True
        return value

    monkeypatch.setattr(transport, "decode_response", decode_then_expire)
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock() + (1000 if expired else 0))
    thread = threading.Thread(target=host_once, args=(mailbox,))
    thread.start()
    try:
        rejected("WORD_EXECUTION_TIMEOUT", transport.call, "external", **arguments("external"))
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(list(mailbox.glob("*/cancel"))) == 1
    assert len(list(mailbox.glob("*/request.json"))) == 1


def test_other_process_lock_rejects_without_publishing_second_job(mailbox):
    import fcntl

    lock = os.open(mailbox / ".client.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rejected("WORD_EXECUTION_BUSY", transport.call, "external", **arguments("external"))
        assert not list(mailbox.glob("*/request.json"))
    finally:
        os.close(lock)


@LINUX
@pytest.mark.parametrize("attack", ["symlink", "mode", "not_directory"])
def test_root_directory_is_private_and_never_follows_links(tmp_path, monkeypatch, attack):
    root = tmp_path / "word-execution"
    if attack == "symlink":
        target = tmp_path / "other"
        target.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
    elif attack == "mode":
        root.mkdir(mode=0o755)
        root.chmod(0o755)
    else:
        root.write_bytes(b"not directory")
    monkeypatch.setattr(transport, "DIRECTORY", root)
    monkeypatch.setattr(transport, "_tmpfs", lambda _: None)
    with pytest.raises((DomainError, OSError)):
        transport._open_directory()


@LINUX
@pytest.mark.parametrize("attack", ["symlink", "hardlink", "fifo", "mode", "owner", "size"])
def test_read_rejects_pathlinks_nonregular_bad_owner_permissions_and_limits(
    tmp_path, monkeypatch, attack
):
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    target = tmp_path / "target"
    target.write_bytes(b"private")
    target.chmod(0o600)
    entry = tmp_path / "response.json"
    if attack == "symlink":
        entry.symlink_to(target)
    elif attack == "hardlink":
        os.link(target, entry)
    elif attack == "fifo":
        os.mkfifo(entry, mode=0o600)
    else:
        entry.write_bytes(b"private")
        entry.chmod(0o644 if attack == "mode" else 0o600)
    if attack == "owner":
        actual = os.geteuid()
        monkeypatch.setattr(transport.os, "geteuid", lambda: actual + 1)
    try:
        with pytest.raises((DomainError, OSError)):
            transport._read(directory, "response.json", 2 if attack == "size" else 100)
        assert target.read_bytes() == b"private"
    finally:
        os.close(directory)


@LINUX
def test_atomic_publication_does_not_replace_existing_or_symlink_target(tmp_path):
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    target = tmp_path / "target"
    target.write_bytes(b"original")
    (tmp_path / "response.json").symlink_to(target)
    try:
        with pytest.raises(FileExistsError):
            transport._publish(directory, "response.json", b"new")
        assert target.read_bytes() == b"original"
        assert not list(tmp_path.glob(".response.json-*"))
    finally:
        os.close(directory)


@LINUX
def test_tmpfs_detection_uses_most_specific_mount(monkeypatch):
    original = Path.read_text

    def mounts(path, **kwargs):
        if str(path) == "/proc/self/mountinfo":
            return "1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n3 2 0:3 / /tmp/word-execution rw - ext4 dev rw\n"
        return original(path, **kwargs)

    monkeypatch.setattr(Path, "read_text", mounts)
    rejected("WORD_EXECUTION_TMPFS_REQUIRED", transport._tmpfs, transport.DIRECTORY)
