"""Desktop transport declarations never expose host private profiles or paid channels."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from deploy import fusion_desktop as control
from deploy import fusion_desktop_compose as desktop
from deploy import fusion_full_spec as spec


@pytest.fixture
def request_value():
    return {
        "version": desktop.VERSION,
        "instance_id": "a" * 32,
        "name": "full_desktop",
        "origin": "http://127.0.0.1:5189",
        "python_image": "synthetic-python@sha256:" + "b" * 64,
        "web_image": "synthetic-web@sha256:" + "c" * 64,
    }


@pytest.fixture
def plan(request_value):
    value = request_value
    return {
        "version": spec.VERSION,
        "deployment_id": "d" * 32,
        "name": value["name"],
        "origin": value["origin"],
        "images": {**spec.IMAGES, "python": value["python_image"], "web": value["web_image"]},
        "topology": {
            "mode": "compose",
            "postgres_host": "postgres",
            "postgres_port": 5432,
            "kafka_bootstrap": "kafka:9092",
            "s3_endpoint": "http://object-store:8333",
        },
        "kafka_cluster_id": "A" * 22,
        "bucket": "fusion-full-" + "d" * 32,
        "ordered_sql": [
            {"path": item.path.replace("\\", "/"), "sha256": item.sha256}
            for item in spec.ordered_sql()
        ],
        "sources": {},
        "frontend": {},
        "policy_sha256": spec.digest((spec.fresh.ROOT / spec.POLICY).read_bytes()),
        "model_configured": False,
        "task_runner_enabled": False,
    }


def test_bootstrap_has_only_a_configurator_and_no_host_password_bind(request_value, tmp_path):
    value = desktop.document(request_value, tmp_path)
    assert set(value["services"]) == {"configure"}
    configure = value["services"]["configure"]
    assert configure["user"] == "0:0" and configure["cap_drop"] == ["ALL"]
    assert configure["cap_add"] == ["CHOWN", "DAC_OVERRIDE"]
    assert configure["networks"] == ["core"] and not configure.get("ports")
    assert all("admin-password" not in str(mount) for mount in configure["volumes"])
    assert not value.get("secrets")


def test_role_credentials_are_separate_linux_volumes_and_app_sources_are_readonly(
    request_value, plan, tmp_path
):
    value = desktop.document(request_value, tmp_path, plan)
    services = value["services"]
    assert value["name"] == desktop.project(request_value)
    api = services["api"]
    assert api["depends_on"] == {"publish": {"condition": "service_completed_successfully"}}
    assert api["user"] == "65532:65532" and api["cap_drop"] == ["ALL"]
    assert api["volumes"][-2:] == [
        desktop.volume("profile_api", "/runtime", readonly=True),
        desktop.volume("api_state", "/workspace/.local"),
    ]
    for name in desktop.full.COMPONENTS:
        service = services[name]
        role = spec.COMMANDS[desktop.full.COMPONENTS[name]][0]
        assert desktop.volume("profile_" + role, "/runtime", readonly=True) in service["volumes"]
        assert not any(
            mount["source"] in {"private_config", "init_state", "owner_secret", "store_secret"}
            for mount in service["volumes"]
        )
        assert all(mount["read_only"] for mount in service["volumes"] if mount["type"] == "bind")
        assert not any(key.endswith("_DSN") or "API_KEY" in key for key in service["environment"])
    assert services["web"]["ports"] == ["127.0.0.1:5189:8080"]
    assert services["postgres"]["command"] == ["postgres", "-c", "jit=off"]
    assert services["object-store"]["command"] == desktop.full.STORE_COMMAND
    assert services["worker-review"]["profiles"] == ["model"]
    assert services["task-runner"]["profiles"] == ["automation"]
    validation = services["validation"]
    assert validation["profiles"] == ["checks"] and validation["user"] == "65532:65532"
    assert not validation.get("cap_add")
    assert {mount["source"] for mount in validation["volumes"] if mount["type"] == "volume"} == {
        "profile_api",
        "validation_login",
    }
    assert all(mount["read_only"] for mount in validation["volumes"])
    assert all(not service.get("ports") for name, service in services.items() if name != "web")


@pytest.mark.parametrize(
    "change", ["port", "owner_mount", "model", "writable_source", "socket", "label"]
)
def test_manifest_tampering_is_rejected(request_value, plan, tmp_path, change):
    value = deepcopy(desktop.document(request_value, tmp_path, plan))
    services = value["services"]
    if change == "port":
        services["postgres"]["ports"] = ["5432:5432"]
    elif change == "owner_mount":
        services["api"]["volumes"].append(desktop.volume("private_config", "/owner", readonly=True))
    elif change == "model":
        services["worker-review"].pop("profiles")
    elif change == "writable_source":
        services["api"]["volumes"][0]["read_only"] = False
    elif change == "socket":
        services["api"]["volumes"].append(desktop.bind("/var/run/docker.sock", "/docker.sock"))
    else:
        services["api"]["labels"]["tender.desktop.instance"] = "e" * 32
    with pytest.raises(spec.ConfigurationError):
        desktop.validate_document(value, request_value, tmp_path, plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", "http://0.0.0.0:5189"),
        ("origin", "https://127.0.0.1:5189"),
        ("origin", "http://127.0.0.1:5189/private"),
        ("python_image", "floating:latest"),
        ("name", "prod"),
        ("instance_id", "../foreign"),
    ],
)
def test_invalid_public_descriptor_never_configures_a_service(
    request_value, field, value, tmp_path
):
    request_value[field] = value
    with pytest.raises(spec.ConfigurationError):
        desktop.document(request_value, tmp_path)


def test_host_launcher_does_not_inherit_model_owner_or_compose_profile(monkeypatch):
    for key in ("OPENAI_API_KEY", "OWNER_DATABASE_DSN", "COMPOSE_PROFILES", "DOCKER_HOST"):
        monkeypatch.setenv(key, "synthetic-must-not-inherit")
    environment = control._environment()
    assert not set(environment) & {
        "OPENAI_API_KEY",
        "OWNER_DATABASE_DSN",
        "COMPOSE_PROFILES",
        "DOCKER_HOST",
    }


def test_host_prepare_is_new_only_and_restricts_directory_to_its_workspace(
    tmp_path, monkeypatch, request_value
):
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    path = tmp_path / ".local/full-desktop/candidate1"
    result = control.prepare(
        path,
        name=request_value["name"],
        origin=request_value["origin"],
        python_image=request_value["python_image"],
        web_image=request_value["web_image"],
    )
    assert result["services_started"] == 0
    assert set(p.name for p in path.iterdir()) == {
        "request.json",
        "bootstrap.compose.json",
        "compose.public.env",
    }
    with pytest.raises(spec.ConfigurationError):
        control.directory(tmp_path / "outside")
    with pytest.raises(spec.ConfigurationError):
        control.prepare(
            path,
            name=request_value["name"],
            origin=request_value["origin"],
            python_image=request_value["python_image"],
            web_image=request_value["web_image"],
        )


def test_linux_public_paths_validate_on_windows_without_rewriting_the_plan(plan, monkeypatch):
    before = deepcopy(plan)
    reviewed = [
        SimpleNamespace(path=item["path"].replace("/", "\\"), sha256=item["sha256"])
        for item in plan["ordered_sql"]
    ]
    monkeypatch.setattr(spec, "ordered_sql", lambda: reviewed)
    desktop.validate_public_plan(plan)
    assert plan == before
    changed = deepcopy(plan)
    changed["ordered_sql"][0]["sha256"] = "0" * 64
    with pytest.raises(spec.ConfigurationError):
        desktop.validate_public_plan(changed)


def test_failed_bootstrap_can_be_stopped_without_private_state_or_volume_deletion(
    tmp_path, monkeypatch, request_value
):
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    path = tmp_path / ".local/full-desktop/candidate1"
    control.prepare(
        path,
        name=request_value["name"],
        origin=request_value["origin"],
        python_image=request_value["python_image"],
        web_image=request_value["web_image"],
    )
    commands = []
    monkeypatch.setattr(control, "_run", lambda command, **kwargs: commands.append(command))
    result = control.observe(path, "stop")
    assert result["bootstrap_only"] and not result["volumes_deleted"]
    assert commands[0][-1] == "stop" and "--volumes" not in commands[0]


@pytest.mark.parametrize(
    "argument",
    ["-iam=false", "-s3.autoCreateBucket=false", "-s3.port.iceberg=0", "-s3.port.lance=0"],
)
def test_store_security_argument_changes_are_rejected(
    request_value, plan, tmp_path, argument, monkeypatch
):
    original = desktop._base

    def changed(*args):
        value = original(*args)
        value["services"]["object-store"]["command"].remove(argument)
        return value

    monkeypatch.setattr(desktop, "_base", changed)
    with pytest.raises(spec.ConfigurationError, match="FULL_STORE_EXECUTION_PROFILE_CHANGED"):
        desktop.document(request_value, tmp_path, plan)
