"""Fusion group configuration and API profile isolation; no daemon or live connection."""

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from deploy.fusion_runtime import API_KEYS, api_environment
from deploy.initialize_database import ROOT


def test_minimal_group_has_no_paid_consumers_or_nonlocal_database_ports():
    plan = yaml.safe_load((ROOT / "deploy/compose.fusion.yaml").read_text(encoding="utf-8"))
    assert plan["name"] == "tender-fusion"
    services = plan["services"]
    assert {name for name, service in services.items() if not service.get("profiles")} == {
        "postgres",
        "init",
        "api",
        "web",
    }
    assert services["web"]["ports"] == ["127.0.0.1:5188:8080"]
    assert services["postgres"].get("ports", []) == []
    assert services["checks-postgres"].get("ports", []) == []
    assert plan["networks"]["core"]["internal"]
    assert plan["networks"]["preview"] == {"driver": "bridge"}
    assert services["web"]["networks"] == ["core", "preview"]
    for name, service in services.items():
        if name != "web":
            assert "preview" not in service["networks"]
    assert set(services) == {"postgres", "init", "api", "web", "checks", "checks-postgres"}
    assert services["checks"]["profiles"] == services["checks-postgres"]["profiles"] == ["checks"]
    assert set(services["checks"]["depends_on"]) == {"checks-postgres"}
    assert "fusion-nonowner-postgres" in services["checks-postgres"]["networks"]["core"]["aliases"]
    for service in services.values():
        assert service["restart"] == "no"
        assert service["pull_policy"] == "never"
        assert service.get("network_mode") != "host" and not service.get("privileged")
        assert "docker.sock" not in str(service.get("volumes", []))
        assert "DEEPSEEK_API_KEY" not in service.get("environment", {})
        assert "POSTGRES_PASSWORD" not in service.get("environment", {})
        assert all(mount.startswith("/") for mount in service.get("tmpfs", []))


def test_api_cannot_mount_owner_state_and_group_checks_are_not_disposable():
    plan = yaml.safe_load((ROOT / "deploy/compose.fusion.yaml").read_text(encoding="utf-8"))
    api = plan["services"]["api"]
    assert "api_profile_v2:/runtime:ro" in api["volumes"]
    assert not any("init_state" in volume or ".env" in volume for volume in api["volumes"])
    assert not any(key.endswith("_DSN") for key in api["environment"])
    assert not api.get("secrets")
    assert plan["services"]["postgres"]["secrets"] == ["fusion_owner_password"]
    assert plan["services"]["checks-postgres"]["secrets"] == ["fusion_checks_owner_password"]
    assert plan["services"]["checks"]["secrets"] == ["fusion_checks_owner_password"]
    assert "init_state_v2:/workspace/.local" in plan["services"]["init"]["volumes"]
    assert "api_profile_v2:/runtime" in plan["services"]["init"]["volumes"]
    assert {"init_state", "api_profile", "init_state_v2", "api_profile_v2"} <= plan[
        "volumes"
    ].keys()
    assert (
        "checks_postgres_data:/var/lib/postgresql/data"
        in plan["services"]["checks-postgres"]["volumes"]
    )
    wrapper = (ROOT / "deploy/fusion.ps1").read_text(encoding="utf-8")
    assert "--project-name', 'tender-fusion'" in wrapper
    assert "run --rm" not in wrapper and "docker run" not in wrapper
    assert "fusion.defaults.env" in wrapper and "--env-file" in wrapper


def private_profile(tmp_path, values):
    profile = tmp_path / "api.env"
    profile.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )
    profile.chmod(0o600)
    return profile


def test_runtime_replaces_inherited_business_credentials_with_one_api_dsn(tmp_path, monkeypatch):
    values = {key: "explicit-synthetic-only" for key in API_KEYS}
    profile = private_profile(tmp_path, values)
    for key in (
        "OWNER_DATABASE_DSN",
        "WORKER_DATABASE_DSN",
        "ASSISTANT_BUDGET_ADMIN_DATABASE_DSN",
        "DEEPSEEK_API_KEY",
        "OBJECT_STORE_SECRET_KEY",
    ):
        monkeypatch.setenv(key, "must-not-leak")
    environment = api_environment(profile)
    assert {key for key in environment if key.endswith("_DATABASE_DSN")} == {"API_DATABASE_DSN"}
    assert all(environment.get(key) != "must-not-leak" for key in environment)
    assert set(values) <= environment.keys()


@pytest.mark.parametrize(
    "extra",
    [
        "OWNER_DATABASE_DSN",
        "WORKER_DATABASE_DSN",
        "ASSISTANT_BUDGET_ADMIN_DATABASE_DSN",
        "DEEPSEEK_API_KEY",
    ],
)
def test_runtime_refuses_extra_or_management_profile_keys(tmp_path, extra):
    values = {key: "synthetic" for key in API_KEYS} | {extra: "forbidden"}
    with pytest.raises(RuntimeError, match="PROFILE_KEYS_INVALID"):
        api_environment(private_profile(tmp_path, values))


def test_runtime_refuses_public_or_symlink_profile(tmp_path):
    profile = private_profile(tmp_path, {key: "synthetic" for key in API_KEYS})
    profile.chmod(0o644)
    with pytest.raises(RuntimeError, match="MUST_BE_PRIVATE"):
        api_environment(profile)
    profile.chmod(0o600)
    link = Path(tmp_path / "linked.env")
    link.symlink_to(profile)
    with pytest.raises(RuntimeError, match="MUST_BE_PRIVATE"):
        api_environment(link)
