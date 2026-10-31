"""POSIX setup file failures; ownership transfer is asserted, then tested in real Compose."""

import json
import os
import sys
from pathlib import Path

import pytest

from deploy import fusion_desktop_compose as desktop
from deploy import fusion_desktop_private as private
from deploy import fusion_full_spec as spec

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="POSIX file-mode checks run in the fixed Linux Compose checks service",
)


def test_infrastructure_secret_is_bound_to_its_dedicated_volume_and_never_repaired(tmp_path):
    directory = tmp_path / "secret"
    directory.mkdir()
    raw = b"synthetic-volume-secret"
    private._secret(directory, "owner-password", raw)
    path = directory / "owner-password"
    assert path.stat().st_mode & 0o777 == 0o444
    private._secret(directory, "owner-password", raw)
    with pytest.raises(spec.ConfigurationError):
        private._secret(directory, "owner-password", b"different-synthetic-value")
    assert path.read_bytes() == raw
    path.chmod(0o600)
    with pytest.raises(spec.ConfigurationError):
        private._secret(directory, "owner-password", raw)
    assert path.stat().st_mode & 0o777 == 0o600


def test_unknown_or_linked_volume_contents_are_rejected(tmp_path):
    directory = tmp_path / "occupied"
    directory.mkdir()
    (directory / "unknown").write_text("synthetic")
    with pytest.raises(spec.ConfigurationError):
        private._secret(directory, "owner-password", b"synthetic")
    linked = tmp_path / "linked"
    linked.symlink_to(directory)
    with pytest.raises(spec.ConfigurationError):
        private._secret(linked, "owner-password", b"synthetic")


def test_role_profile_is_private_and_only_the_fixed_runtime_uid_receives_it(tmp_path, monkeypatch):
    target = tmp_path / "profile"
    target.mkdir()
    chowns = []
    monkeypatch.setattr(
        private.os, "chown", lambda path, uid, gid: chowns.append((Path(path), uid, gid))
    )
    private._profile(target, b'{"synthetic":true}')
    assert private.UID == 65532
    assert chowns == [(target, 65532, 65532), (target / "profile.json", 65532, 65532)]
    assert target.stat().st_mode & 0o777 == 0o700
    assert (target / "profile.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(spec.ConfigurationError):
        private._profile(target, b"different")
    assert (target / "profile.json").read_bytes() == b'{"synthetic":true}'


@pytest.fixture
def configuring(tmp_path, monkeypatch):
    from deploy import fusion_full_configure, fusion_full_dependencies

    root = tmp_path / "private"
    public = tmp_path / "public"
    root.mkdir()
    public.mkdir()
    path = root / "deployment"
    request = {
        "version": desktop.VERSION,
        "instance_id": "a" * 32,
        "name": "full_synthetic",
        "origin": "http://127.0.0.1:5189",
        "python_image": "synthetic-python@sha256:" + "b" * 64,
        "web_image": "synthetic-web@sha256:" + "c" * 64,
    }
    (public / "request.json").write_text(json.dumps(request))
    value = {
        "plan": {"model_configured": False, "task_runner_enabled": False},
        "plan_digest": "d" * 64,
    }
    captured = []

    def create(directory, **kwargs):
        captured.append(kwargs)
        value["admin_password"] = kwargs["admin_password"]
        value["model"] = kwargs.get("model")
        value["plan"]["model_configured"] = kwargs.get("model") is not None
        directory.mkdir(mode=0o700)
        spec.write_private(directory / "operator.json", value)
        spec.write_private(directory / "owner-password", b"synthetic-owner-only")
        spec.write_private(directory / "s3-identities.json", b'{"synthetic":true}')

    monkeypatch.setattr(private, "PRIVATE", path)
    monkeypatch.setattr(private, "PUBLIC", public)
    monkeypatch.setattr(fusion_full_configure, "configure", create)
    monkeypatch.setattr(fusion_full_dependencies, "identity", lambda: {"synthetic": True})
    monkeypatch.setattr(
        private,
        "_binding",
        lambda: (value, {"request": request, "plan_digest": value["plan_digest"]}),
    )
    writes = []
    monkeypatch.setattr(private, "_secret", lambda *args: writes.append(args))
    captured.append({"secret_writes": writes})
    return path, public, request, value, captured


def test_configuration_generates_strong_admin_locally_without_exporting_it(configuring):
    path, public, request, value, captured = configuring
    result = private.configure()
    assert len(captured) == 2 and len(captured[1]["admin_password"]) >= 32
    writes = captured[0]["secret_writes"]
    assert writes[0] == (Path("/owner-secret"), "owner_password", b"synthetic-owner-only")
    assert writes[1][0:2] == (Path("/store-secret"), "s3-identities.json")
    assert result["private_values_exported"] is False
    assert json.loads((public / "public-plan.json").read_bytes()) == value["plan"]
    assert "admin_password" not in (public / "public-plan.json").read_text()
    assert path.stat().st_mode & 0o777 == 0o700
    assert (path / "desktop-binding.json").stat().st_mode & 0o777 == 0o600
    private.configure()
    assert len(captured) == 2


def test_changed_public_or_private_binding_is_not_reconfigured(configuring):
    path, public, request, value, captured = configuring
    private.configure()
    request["origin"] = "http://127.0.0.1:5190"
    with pytest.raises(spec.ConfigurationError):
        private.configure()
    assert len(captured) == 2


def test_existing_admin_policy_and_other_secret_minimum_are_unchanged(tmp_path):
    from deploy.fusion_full_configure import configure

    with pytest.raises(spec.ConfigurationError, match="FULL_ADMIN_PASSWORD_REQUIRED"):
        configure(
            tmp_path / "uncreated",
            name="full_synthetic",
            origin="http://127.0.0.1:5189",
            python_image="synthetic-python@sha256:" + "b" * 64,
            web_image="synthetic-web@sha256:" + "c" * 64,
            admin_password="x" * 6,
        )


def directory_owner(monkeypatch, directory, uid):
    """Model the container volume's owner while retaining real file modes and IO."""
    original = Path.stat

    def owned(path, *args, **kwargs):
        information = original(path, *args, **kwargs)
        if path != directory:
            return information
        fields = list(information)
        fields[4] = uid
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", owned)


def test_new_init_volume_is_private_but_existing_bad_permissions_are_not_repaired(
    tmp_path, monkeypatch
):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o755)
    # The deployed initializer receives a root-owned volume. Unit runners may
    # have another UID; simulate only ownership, keeping actual chmod/read IO.
    directory_owner(monkeypatch, directory, 0)
    private._initial_state(directory)
    assert directory.stat().st_mode & 0o777 == 0o700
    (directory / "already-initialized").write_text("synthetic")
    directory.chmod(0o755)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_INIT_STATE_CHANGED"):
        private._initial_state(directory)
    assert directory.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("initialized", (False, True))
def test_init_volume_with_nonroot_owner_is_rejected_without_repair(
    tmp_path, monkeypatch, initialized
):
    directory = tmp_path / "nonroot-state"
    directory.mkdir(mode=0o755)
    # mkdir's requested mode is masked by the runner's umask (often 0077).
    # Start with the exact nonprivate fixture mode so an illicit chmod(0700)
    # during rejection remains observable on both local and CI runners.
    directory.chmod(0o755)
    if initialized:
        (directory / "already-initialized").write_text("synthetic")
    directory_owner(monkeypatch, directory, 1001)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_INIT_STATE_REQUIRED"):
        private._initial_state(directory)
    assert directory.stat().st_mode & 0o777 == 0o755
    assert bool(list(directory.iterdir())) is initialized


@pytest.mark.parametrize("mode,accepted", ((0o700, True), (0o755, False)))
def test_empty_application_state_is_not_repaired_after_ownership_transfer(
    tmp_path, monkeypatch, mode, accepted
):
    state = tmp_path / "api-state"
    state.mkdir()
    state.chmod(mode)
    original = Path.stat

    def owned(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == state:
            fields = list(info)
            fields[4] = fields[5] = private.UID
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, "stat", owned)

    def forbidden(*_):
        raise AssertionError("An already transferred volume must not be chmod/chowned")

    monkeypatch.setattr(Path, "chmod", forbidden)
    monkeypatch.setattr(private.os, "chown", forbidden)
    if accepted:
        private._application_state(state)
    else:
        with pytest.raises(spec.ConfigurationError, match="DESKTOP_API_STATE_CHANGED"):
            private._application_state(state)
    assert state.stat().st_mode & 0o777 == mode


def test_unknown_empty_api_state_owner_is_rejected_without_repair(tmp_path, monkeypatch):
    state = tmp_path / "api-state"
    state.mkdir(mode=0o700)
    directory_owner(monkeypatch, state, 1234)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_API_STATE_CHANGED"):
        private._application_state(state)


def test_explicit_admin_is_private_and_never_resets_existing_secret(configuring):
    path, public, request, value, captured = configuring
    supplied = {"admin_password": "synthetic-bootstrap-password", "model": None}
    private.configure(supplied)
    assert captured[1]["admin_password"] == supplied["admin_password"]
    assert "model" not in captured[1]
    private.configure(supplied)
    private.configure()
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_BINDING_CHANGED"):
        private.configure(supplied | {"admin_password": "different-synthetic-password"})
    assert len(captured) == 2
    assert supplied["admin_password"] not in (public / "public-plan.json").read_text()


def test_model_payload_is_required_only_for_new_declared_installation(configuring, monkeypatch):
    path, public, request, value, captured = configuring
    request["model_configured"] = True
    # Root owns the new public schema; this test isolates private-stage handling.
    monkeypatch.setattr(desktop, "validate_request", lambda value: request)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_MODEL_REQUIRED"):
        private.configure()
    assert not path.exists() and len(captured) == 1
    model = {
        "DEEPSEEK_API_KEY": "synthetic-not-a-real-key",
        "DEEPSEEK_MODEL": "deepseek-flash",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
    }
    supplied = {"admin_password": None, "model": model}
    private.configure(supplied)
    assert captured[1]["model"] == model
    private.configure()
    private.configure(supplied)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_BINDING_CHANGED"):
        private.configure(
            {"admin_password": None, "model": model | {"DEEPSEEK_API_KEY": "other-synthetic-key"}}
        )
    assert len(captured) == 2
    assert "synthetic-not-a-real-key" not in (public / "public-plan.json").read_text()


def test_model_cannot_be_injected_into_undeclared_installation(configuring):
    path, public, request, value, captured = configuring
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_MODEL_INTENT_MISMATCH"):
        private.configure(
            {
                "admin_password": None,
                "model": {
                    "DEEPSEEK_API_KEY": "synthetic-key",
                    "DEEPSEEK_MODEL": "deepseek-flash",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
                },
            }
        )
    assert not path.exists() and len(captured) == 1
