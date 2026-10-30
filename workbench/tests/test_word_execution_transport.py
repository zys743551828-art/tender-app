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


def arguments():
    return {
        "source": b"synthetic DOCX \x00\xff",
        "requested_fonts": ["Arial", "Noto Sans", "Arial"],
    }


def result():
    from packages.word_intake import prebuilt

    return {
        "pdf": b"%PDF-synthetic\x00\xff",
        "font_facts": {
            "matches": [
                {"requested": name, "families": name} for name in arguments()["requested_fonts"]
            ],
            "charset": "20-7e 4e00-9fff\n",
        },
        "isolation": {"checks": {"network_none": True}},
        "conversion_attempted": True,
        "error_code": None,
        "source_docx_digest": transport._sha(arguments()["source"]),
        "image_reference": prebuilt.IMAGE,
        "image_id": prebuilt.IMAGE_ID,
        "cleanup_confirmed": True,
        "resource_receipt": {"closed": True, "receipts": [{"closed": True}]},
    }


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def rejected(code, function, *args, **kwargs):
    with pytest.raises(DomainError) as error:
        function(*args, **kwargs)
    assert error.value.code == code


def test_complete_explicit_binary_round_trip():
    supplied = arguments()
    raw = transport._request(supplied)
    request = transport.decode_request(raw)
    assert request["arguments"] == supplied
    assert request["operation"] == "convert_docx"
    assert len(request["request_id"]) == 32
    expected = result()
    assert transport.decode_response(raw, transport.encode_response(raw, expected)) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", "word-render-execution/1"),
        ("request_id", "../outside"),
        ("operation", "shell"),
        ("lane", "page"),
    ],
)
def test_request_envelope_is_closed(field, value):
    wire = json.loads(transport._request(arguments()))
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
    "slot",
    [
        "snapshot",
        "profile",
        "materials",
        "producer_manifest",
        "iterations",
        "receipt",
        "command",
        "image",
        "url",
    ],
)
def test_high_level_or_caller_control_slots_are_not_supported(slot):
    value = arguments() | {slot: {}}
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport._request, value)


@pytest.mark.parametrize("fonts", [["-option"], ["bad/name"], ["a" * 129], [1], ["x\n"], "Arial"])
def test_invalid_font_names_are_rejected(fonts):
    rejected(
        "WORD_EXECUTION_LIMIT" if type(fonts) is not list else "WORD_EXECUTION_PROTOCOL_INVALID",
        transport._request,
        arguments() | {"requested_fonts": fonts},
    )


@pytest.mark.parametrize("attack", ["digest", "size", "alphabet", "noncanonical", "unknown"])
def test_binary_slot_length_digest_and_canonical_base64_are_checked(attack):
    wire = json.loads(transport._request({"source": b"a", "requested_fonts": []}))
    slot = wire["arguments"]["source"]
    if attack == "digest":
        slot["sha256"] = "0" * 64
    elif attack == "size":
        slot["byte_size"] = 2
    elif attack == "alphabet":
        slot["base64"] = "!!!!"
    elif attack == "noncanonical":
        slot["base64"] = "YR=="
    else:
        slot["path"] = "not allowed"
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_request, dump(wire))


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", "wrong"),
        ("request_id", "0" * 32),
        ("operation", "page"),
        ("request_sha256", "0" * 64),
    ],
)
def test_response_identity_and_exact_raw_request_binding(field, value):
    request = transport._request(arguments())
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_docx_digest", "0" * 64),
        ("image_reference", "other"),
        ("image_id", "other"),
        ("font_facts", {"matches": [], "charset": "20-7e"}),
    ],
)
def test_raw_result_is_bound_to_source_image_and_exact_font_requests(field, value):
    request = transport._request(arguments())
    response = json.loads(transport.encode_response(request, result()))
    response["result"][field] = value
    rejected("WORD_EXECUTION_RESPONSE_MISMATCH", transport.decode_response, request, dump(response))


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("font_facts", None, "WORD_EXECUTION_PROTOCOL_INVALID"),
        ("cleanup_confirmed", False, "WORD_EXECUTION_CLEANUP_UNCONFIRMED"),
        ("resource_receipt", None, "WORD_EXECUTION_CLEANUP_UNCONFIRMED"),
        (
            "resource_receipt",
            {"closed": True, "receipts": []},
            "WORD_EXECUTION_CLEANUP_UNCONFIRMED",
        ),
        (
            "resource_receipt",
            {"closed": True, "receipts": [{"closed": False}]},
            "WORD_EXECUTION_CLEANUP_UNCONFIRMED",
        ),
        ("coverage", "complete", "WORD_EXECUTION_PROTOCOL_INVALID"),
        ("render_iterations", [], "WORD_EXECUTION_PROTOCOL_INVALID"),
    ],
)
def test_raw_success_never_loses_facts_cleanup_or_accepts_qualification(field, value, code):
    rejected(
        code, transport.encode_response, transport._request(arguments()), result() | {field: value}
    )


def test_error_response_never_becomes_conversion_success():
    request = transport._request(arguments())
    raw = transport.encode_error(request, "WORD_CONVERSION_TIMEOUT")
    rejected("WORD_CONVERSION_TIMEOUT", transport.decode_response, request, raw)
    rejected(
        "WORD_EXECUTION_PROTOCOL_INVALID", transport.encode_error, request, "private detail /path"
    )
    response = json.loads(raw)
    response["result"] = json.loads(transport.encode_response(request, result()))["result"]
    rejected("WORD_EXECUTION_PROTOCOL_INVALID", transport.decode_response, request, dump(response))
    failed = result() | {
        "pdf": None,
        "font_facts": None,
        "isolation": None,
        "error_code": "WORD_CONVERSION_TIMEOUT",
    }
    assert transport.decode_response(request, transport.encode_response(request, failed)) == failed


def test_wire_and_font_fact_limits(monkeypatch):
    request = transport._request(arguments())
    monkeypatch.setattr(transport, "MAX_REQUEST_BYTES", 10)
    rejected("WORD_EXECUTION_LIMIT", transport.decode_request, request)
    monkeypatch.setattr(transport, "MAX_REQUEST_BYTES", 160 * 1024 * 1024)
    monkeypatch.setattr(transport, "MAX_SOURCE_BYTES", 2)
    rejected("WORD_EXECUTION_LIMIT", transport._request, arguments())
    monkeypatch.setattr(transport, "MAX_SOURCE_BYTES", 100 * 1024 * 1024)
    monkeypatch.setattr(transport, "MAX_PDF_BYTES", 2)
    rejected("WORD_EXECUTION_LIMIT", transport.encode_response, request, result())
    monkeypatch.setattr(transport, "MAX_PDF_BYTES", 50 * 1024 * 1024)
    monkeypatch.setattr(transport, "MAX_CHARSET_CHARS", 2)
    rejected("WORD_EXECUTION_LIMIT", transport.encode_response, request, result())
    assert transport.MAX_SOURCE_BYTES == 100 * 1024 * 1024
    assert transport.MAX_PDF_BYTES == 50 * 1024 * 1024


def test_default_native_and_invalid_configuration(monkeypatch):
    monkeypatch.delenv(transport.ENVIRONMENT_KEY, raising=False)
    assert transport.enabled() is False
    with transport.deadline_budget(0):
        assert transport._DEADLINE.get() is None
    rejected("WORD_EXECUTION_NOT_CONFIGURED", transport.call_conversion, **arguments())
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
            response = transport.encode_response(request, result())
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


def test_mailbox_roundtrip_and_exact_success_cleanup(mailbox):
    thread = threading.Thread(target=host_once, args=(mailbox,))
    thread.start()
    try:
        assert transport.call_conversion(**arguments()) == result()
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
        rejected(code, transport.call_conversion, **arguments())
    finally:
        thread.join(timeout=5)
    assert len(list(mailbox.glob("*/cancel"))) == 1


def test_timeout_never_accepts_late_response_or_claims_cleanup(mailbox, monkeypatch):
    monkeypatch.setattr(transport, "CONVERSION_TIMEOUT", 0.03)
    rejected("WORD_EXECUTION_TIMEOUT", transport.call_conversion, **arguments())
    job = next(mailbox.glob("*/cancel")).parent
    raw = (job / "request.json").read_bytes()
    response = transport.encode_response(raw, result())
    (job / "response.json").write_bytes(response)
    assert (job / "cancel").exists()
    # A new UUID request cannot consume the previous job's late response.
    rejected("WORD_EXECUTION_TIMEOUT", transport.call_conversion, **arguments())
    assert len(list(mailbox.glob("*/cancel"))) == 2


def test_keyboard_interrupt_revokes_without_claiming_executor_stopped(mailbox, monkeypatch):
    def interrupted(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(transport.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        transport.call_conversion(**arguments())
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
        rejected("WORD_EXECUTION_TIMEOUT", transport.call_conversion, **arguments())
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
        rejected("WORD_EXECUTION_BUSY", transport.call_conversion, **arguments())
        assert not list(mailbox.glob("*/request.json"))
    finally:
        os.close(lock)


def test_nested_budget_never_extends_and_expired_budget_publishes_nothing(mailbox, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    with pytest.raises(DomainError) as expired:
        with transport.deadline_budget(240):
            assert transport._DEADLINE.get() == 340
            with transport.deadline_budget(500):
                assert transport._DEADLINE.get() == 340
            with transport.deadline_budget(120):
                assert transport._DEADLINE.get() == 220
            now[0] = 341
            rejected("WORD_EXECUTION_TIMEOUT", transport.call_conversion, **arguments())
            assert not list(mailbox.iterdir())
    assert expired.value.code == "WORD_EXECUTION_TIMEOUT"
    assert transport._DEADLINE.get() is None


def test_budget_covers_local_work_and_preserves_original_exception(mailbox, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    with pytest.raises(DomainError) as expired:
        with transport.deadline_budget(120):
            now[0] = 221
    assert expired.value.code == "WORD_EXECUTION_TIMEOUT"
    assert transport._DEADLINE.get() is None
    with pytest.raises(ValueError, match="original"):
        with transport.deadline_budget(120):
            now[0] += 121
            raise ValueError("original")
    assert transport._DEADLINE.get() is None


@pytest.mark.parametrize("remaining,expected", [(30, 30), (240, 120)])
def test_conversion_wait_uses_smaller_remaining_budget_and_single_attempt_cap(
    mailbox, monkeypatch, remaining, expected
):
    now = 100.0
    monkeypatch.setattr(transport.time, "monotonic", lambda: now)
    calls = []

    class BusyLock:
        def acquire(self, *, timeout):
            calls.append(timeout)
            return False

    monkeypatch.setattr(transport, "_LOCK", BusyLock())
    with transport.deadline_budget(remaining):
        rejected("WORD_EXECUTION_TIMEOUT", transport.call_conversion, **arguments())
    assert calls == [expected]
    assert not list(mailbox.iterdir())


def test_request_encoding_time_consumes_budget_before_publication(mailbox, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    original = transport._request

    def slow_encode(*args, **kwargs):
        raw = original(*args, **kwargs)
        now[0] += 121
        return raw

    monkeypatch.setattr(transport, "_request", slow_encode)
    rejected("WORD_EXECUTION_TIMEOUT", transport.call_conversion, **arguments())
    assert not list(mailbox.iterdir())


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
