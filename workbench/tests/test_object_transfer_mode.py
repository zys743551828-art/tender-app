"""Transport mode cannot turn an internal store address into a browser URL."""

import pytest

from packages.domain.object_transfer_mode import same_origin
from packages.domain.runtime import DomainError


def configured(backend="s3"):
    return {
        "OBJECT_STORE_BACKEND": backend,
        "OBJECT_TRANSFER_MODE": "same_origin",
        "OBJECT_STORE_ENDPOINT": "http://object-store:8333",
        "OBJECT_STORE_BUCKET": "synthetic-private-bucket",
        "OBJECT_STORE_ACCESS_KEY": "synthetic-access-key",
        "OBJECT_STORE_SECRET_KEY": "synthetic-secret-key",
    }


@pytest.mark.parametrize("backend,expected", [("oss", True), ("s3", False), (None, False)])
def test_absent_switch_preserves_existing_mode(backend, expected):
    values = {"OBJECT_STORE_BACKEND": backend} if backend else {}
    assert same_origin(values) is expected


@pytest.mark.parametrize("backend", ["s3", "oss"])
def test_explicit_mode_is_only_a_boolean_and_never_reads_or_signs_storage(monkeypatch, backend):
    from packages.domain import storage

    def forbidden(*args, **kwargs):
        raise AssertionError("mode selection must not perform storage operations")

    monkeypatch.setattr(storage, "client", forbidden)
    monkeypatch.setattr(storage, "sign", forbidden)
    assert same_origin(configured(backend)) is True


@pytest.mark.parametrize(
    "mode",
    ["", "direct", "SAME_ORIGIN", "http://proxy.internal/secret", " same_origin", "same_origin\n"],
)
def test_unknown_mode_never_falls_back_to_a_presigned_url(mode):
    with pytest.raises(DomainError) as error:
        same_origin(configured() | {"OBJECT_TRANSFER_MODE": mode})
    assert error.value.code == "OBJECT_TRANSFER_MODE_INVALID"
    assert mode not in str(error.value) or mode == ""


@pytest.mark.parametrize(
    "key",
    [
        "OBJECT_STORE_BACKEND",
        "OBJECT_STORE_ENDPOINT",
        "OBJECT_STORE_BUCKET",
        "OBJECT_STORE_ACCESS_KEY",
        "OBJECT_STORE_SECRET_KEY",
    ],
)
def test_explicit_mode_requires_actual_supported_configuration(key):
    values = configured()
    del values[key]
    with pytest.raises(DomainError, match="同源原件传输需要") as error:
        same_origin(values)
    assert error.value.status == 503


@pytest.mark.parametrize("value", ["", "  ", "secret\n", "secret\r", "secret\x00"])
def test_invalid_credentials_are_rejected_without_echo(value):
    with pytest.raises(DomainError) as error:
        same_origin(configured() | {"OBJECT_STORE_SECRET_KEY": value})
    assert error.value.code == "OBJECT_TRANSFER_STORE_NOT_CONFIGURED"
    assert "secret" not in str(error.value)


def test_default_environment_uses_the_same_strict_switch(monkeypatch):
    for key, value in configured().items():
        monkeypatch.setenv(key, value)
    assert same_origin()
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local_files")
    with pytest.raises(DomainError):
        same_origin()
