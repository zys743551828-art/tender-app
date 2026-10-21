"""Closed deployment identities and startup eligibility without any service or fee."""

import copy
import json

import pytest
from psycopg.conninfo import make_conninfo

from deploy import fusion_full_control as control
from deploy import fusion_full_dependencies as dependencies
from deploy import fusion_full_init as initialize
from deploy import fusion_full_runtime as runtime
from deploy import fusion_full_spec as spec
from deploy.fusion_full_configure import configure

PYTHON_IMAGE = "synthetic-unexecuted-python@sha256:" + "a" * 64
WEB_IMAGE = "synthetic-unexecuted-web@sha256:" + "b" * 64


@pytest.fixture
def configured(tmp_path):
    directory = tmp_path / "private"
    configure(
        directory,
        name="full_boundary",
        origin="http://127.0.0.1:5189",
        python_image=PYTHON_IMAGE,
        web_image=WEB_IMAGE,
        admin_password="synthetic-password-only",
    )
    return directory


def sample_profiles(directory):
    value = initialize.operator(directory)
    plan = value["plan"]
    name = plan["name"]
    logins = {role: "twb_checks_" + name + "_01234567_" + role for role in ("api", "worker")}
    receipt = {
        "database": "tender_checks_" + name,
        "logins": logins,
        "object_store_prefix": "fusion-full/"
        + plan["deployment_id"]
        + "/check-environments/synthetic/",
    }
    business = {
        role.upper() + "_DATABASE_DSN": make_conninfo(
            dbname=receipt["database"],
            user=login,
            password="synthetic-private-dsn",
            host="postgres",
            port=5432,
        )
        for role, login in logins.items()
    }
    marker = {
        "key": "runtime-binding/" + plan["deployment_id"] + ".json",
        "bytes": b"synthetic-marker",
    }
    return initialize.profiles(value, receipt, business, marker)


def test_configuration_starts_nothing_and_has_no_paid_or_automation_profile(configured):
    result = control.validate(configured)
    assert result["containers_started"] == result["provider_calls"] == 0
    assert result["docker_validation_performed"] is False
    assert result["sql_count"] == len(spec.fresh.BASE_SQL) + len(spec.EXTENSIONS)
    assert set(result["selected_services"]) == {
        "postgres",
        "kafka",
        "object-store",
        "init",
        "api",
        "web",
        "relay",
        "reconcile",
        "worker-document",
        "worker-export",
        "worker-comparison",
        "build-controller",
        "word-controller",
    }
    values = initialize.operator(configured)
    assert values["plan"]["model_configured"] is False
    assert values["plan"]["task_runner_enabled"] is False
    for path in configured.iterdir():
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    public_env = (configured / "compose.env").read_text()
    assert values["owner_password"] not in public_env
    assert values["store_credentials"]["api"]["secret_key"] not in public_env


@pytest.mark.parametrize(
    "feature,code",
    [("model", "FULL_MODEL_PROFILE_REQUIRED"), ("automation", "FULL_TASK_RUNNER_DISABLED")],
)
def test_selected_features_require_separate_configuration(configured, feature, code):
    with pytest.raises(spec.ConfigurationError, match=code):
        control.validate(configured, **{feature: True})


def test_nonowner_role_profiles_never_inherit_foreign_credentials_or_test_switches(
    configured, monkeypatch
):
    profiles = sample_profiles(configured)
    for name in (
        "OWNER_DATABASE_DSN",
        "WORKER_DATABASE_DSN",
        "API_DATABASE_DSN",
        "ASSISTANT_BUDGET_ADMIN_DSN",
        "DEEPSEEK_API_KEY",
        "HTTP_PROXY",
        "PYTHONHOME",
        "PYTHONPATH",
        "RAG_RUNTIME_TOKEN",
        "WORD_RENDER_PROFILE_PATH",
        "ENABLE_EXPLICIT_MOCK",
    ):
        monkeypatch.setenv(name, "inherited-untrusted-value")
    for component in (
        "api",
        "document",
        "export",
        "comparison",
        "relay",
        "reconcile",
        "build-controller",
        "word-controller",
    ):
        role = spec.COMMANDS[component][0]
        environment = runtime.environment(profiles[role], component)
        assert "inherited-untrusted-value" not in environment.values()
        dsns = [key for key in environment if key.endswith("_DSN")]
        assert dsns == [
            "WORKER_DATABASE_DSN"
            if role in {"worker", "relay", "reconcile"}
            else "API_DATABASE_DSN"
        ]
        assert not any(key in environment for key in spec.MODEL_KEYS)
        assert environment["WORKBENCH_ENV_FILE"] == "explicit-fusion-full-runtime"
    assert profiles["api"]["environment"]["OBJECT_TRANSFER_MODE"] == "same_origin"
    assert profiles["api"]["environment"]["WORD_INTAKE_ENABLED"] == "1"
    assert "OBJECT_STORE_SECRET_KEY" not in profiles["relay"]["environment"]
    assert "KAFKA_BOOTSTRAP_SERVERS" not in profiles["api"]["environment"]


@pytest.mark.parametrize(
    "case",
    [
        "owner",
        "foreign_dsn",
        "model",
        "unknown",
        "remote_s3",
        "wrong_bucket",
        "wrong_cluster",
        "word_off",
        "direct_transfer",
        "runtime",
        "role",
        "extra_login_option",
    ],
)
def test_role_drift_rejected_before_any_connection(configured, case):
    profile = copy.deepcopy(sample_profiles(configured)["api"])
    environment = profile["environment"]
    if case == "owner":
        profile["login"] = "postgres"
    elif case == "foreign_dsn":
        environment["WORKER_DATABASE_DSN"] = environment["API_DATABASE_DSN"]
    elif case == "model":
        environment["DEEPSEEK_API_KEY"] = "unrequested-key"
    elif case == "unknown":
        environment["NEW_SWITCH"] = "1"
    elif case == "remote_s3":
        environment["OBJECT_STORE_ENDPOINT"] = "https://unexpected.invalid"
    elif case == "wrong_bucket":
        environment["OBJECT_STORE_BUCKET"] = "another-environment"
    elif case == "wrong_cluster":
        profile["plan"]["topology"]["kafka_bootstrap"] = "other:9092"
        profile["plan_digest"] = spec.digest(profile["plan"])
    elif case == "word_off":
        environment["WORD_INTAKE_ENABLED"] = "0"
    elif case == "direct_transfer":
        environment["OBJECT_TRANSFER_MODE"] = "direct"
    elif case == "runtime":
        profile["runtime"]["python"] = "0.0.0"
    elif case == "role":
        profile["role"] = "worker"
    else:
        environment["API_DATABASE_DSN"] += " options=-csession_replication_role=replica"
    with pytest.raises(spec.ConfigurationError):
        runtime.environment(profile, "api")


def test_source_schema_frontend_and_runtime_pins_are_rechecked(configured, monkeypatch):
    plan = initialize.operator(configured)["plan"]
    changed = copy.deepcopy(plan)
    changed["ordered_sql"][-1]["sha256"] = "f" * 64
    with pytest.raises(spec.ConfigurationError, match="FULL_SCHEMA_OR_POLICY_CHANGED"):
        spec.validate_plan(changed)
    monkeypatch.setattr(spec, "sources", lambda: {"different": "f" * 64})
    with pytest.raises(spec.ConfigurationError, match="FULL_RUNTIME_SOURCE_CHANGED"):
        spec.validate_plan(plan)
    monkeypatch.setattr(spec, "sources", lambda: plan["sources"])
    monkeypatch.setattr(spec, "frontend", lambda: {"different": "f" * 64})
    with pytest.raises(spec.ConfigurationError, match="FULL_FRONTEND_BUILD_CHANGED"):
        spec.validate_plan(plan, check_frontend=True)
    monkeypatch.setattr(dependencies.importlib.metadata, "version", lambda name: "0.0.0")
    with pytest.raises(spec.ConfigurationError, match="FULL_DEPENDENCY_VERSION_CHANGED"):
        dependencies.identity()


def test_private_inputs_cannot_be_symlinked_or_world_readable(configured, tmp_path):
    profile = configured / "operator.json"
    profile.chmod(0o644)
    with pytest.raises(spec.ConfigurationError, match="FULL_PROFILE_PRIVATE_FILE_REQUIRED"):
        initialize.operator(configured)
    profile.chmod(0o600)
    link = tmp_path / "linked"
    link.symlink_to(profile)
    with pytest.raises(spec.ConfigurationError, match="FULL_PROFILE_PRIVATE_FILE_REQUIRED"):
        spec.load_private_json(link)


def test_operator_model_configuration_does_not_borrow_ambient_key(configured, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ambient-unrequested-provider-key")
    assert initialize.operator(configured)["model"] is None
    assert "paid_worker" not in sample_profiles(configured)
    for value in (
        {"DEEPSEEK_API_KEY": "synthetic-only"},
        {
            "DEEPSEEK_API_KEY": "synthetic-only",
            "DEEPSEEK_MODEL": "mock",
            "DEEPSEEK_BASE_URL": "http://127.0.0.1:12345",
        },
    ):
        with pytest.raises(spec.ConfigurationError):
            spec.validate_model(value)


def test_compose_public_values_cannot_be_swapped_or_augmented(configured):
    path = configured / "compose.env"
    with path.open("a") as output:
        output.write("OWNER_DATABASE_DSN=" + json.dumps("must-not-be-expanded") + "\n")
    with pytest.raises(spec.ConfigurationError, match="FULL_COMPOSE_VARIABLE_BINDING_CHANGED"):
        control.validate(configured)


def test_same_display_name_in_two_private_directories_has_distinct_compose_projects(
    configured, tmp_path
):
    other = tmp_path / "other-private"
    configure(
        other,
        name="full_boundary",
        origin="http://127.0.0.1:5190",
        python_image=PYTHON_IMAGE,
        web_image=WEB_IMAGE,
        admin_password="synthetic-password-only",
    )
    first, second = control.validate(configured), control.validate(other)
    assert first["project"] != second["project"]
    assert first["project"].startswith("tender-full-boundary-")
    assert second["project"].startswith("tender-full-boundary-")


@pytest.mark.parametrize(
    "status,body,ready",
    [
        (
            200,
            {"database": "ready", "model": "not_configured", "slice": "pdf-and-core-review"},
            True,
        ),
        (200, {"ready": True}, False),
        (503, {"database": "ready", "model": "configured", "slice": "pdf-and-core-review"}, False),
        (302, {}, False),
    ],
)
def test_http_health_requires_an_actual_correct_loopback_response(monkeypatch, status, body, ready):
    observations = []

    class Connection:
        def __init__(self, host, port, timeout):
            observations.append((host, port, timeout))

        def request(self, method, path):
            observations.append((method, path))

        def getresponse(self):
            from types import SimpleNamespace

            return SimpleNamespace(status=status, read=lambda maximum: json.dumps(body).encode())

        def close(self):
            observations.append("closed")

    monkeypatch.setattr(runtime, "HTTPConnection", Connection)
    monkeypatch.setenv("HTTP_PROXY", "http://must-not-contact.invalid")
    if ready:
        assert runtime.http_ready()["listener_verified"] is True
    else:
        with pytest.raises(spec.ConfigurationError, match="FULL_API_HTTP_NOT_READY"):
            runtime.http_ready()
    assert observations == [("127.0.0.1", 8000, 3), ("GET", "/health/ready"), "closed"]


def test_http_health_closed_listener_is_unavailable(monkeypatch):
    class Closed:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args):
            raise ConnectionRefusedError

        def close(self):
            pass

    monkeypatch.setattr(runtime, "HTTPConnection", Closed)
    with pytest.raises(spec.ConfigurationError, match="FULL_API_HTTP_NOT_READY"):
        runtime.http_ready()


def test_native_launcher_accepts_only_two_fixed_suites():
    from types import SimpleNamespace

    from deploy.fusion_full_native import SUITES, run

    assert SUITES == {
        "native": ("tests/test_fusion_full_native.py", 240),
        "transport-faults": ("tests/test_real_transport_fault_recovery.py", 480),
    }
    with pytest.raises(spec.ConfigurationError, match="FULL_NATIVE_SUITE_INVALID"):
        run(SimpleNamespace(suite="../../other-command"))


@pytest.mark.parametrize(
    "case",
    [
        "port",
        "owner_mount",
        "source_write",
        "extra_mount",
        "model_default",
        "model_egress",
        "scheduler_default",
        "foreign_env",
    ],
)
def test_compose_capability_injection_is_rejected(configured, case):
    import yaml

    plan = initialize.operator(configured)["plan"]
    values = control._values(configured, plan)
    document = yaml.safe_load(
        control._VARIABLE.sub(lambda match: values[match.group(1)], control.COMPOSE.read_text())
    )
    service = document["services"]
    if case == "port":
        service["postgres"]["ports"] = ["5432:5432"]
    elif case == "owner_mount":
        service["api"]["volumes"].append(str(configured) + "/state:/owner:ro")
    elif case == "source_write":
        service["api"]["volumes"][0] = "../packages:/workspace/packages"
    elif case == "extra_mount":
        service["api"]["volumes"].append("/etc:/foreign:ro")
    elif case == "model_default":
        del service["worker-review"]["profiles"]
    elif case == "model_egress":
        service["worker-document"]["networks"] = ["core", "model_egress"]
    elif case == "scheduler_default":
        del service["task-runner"]["profiles"]
    else:
        service["api"]["environment"] = dict(
            service["api"]["environment"], OWNER_DATABASE_DSN="forbidden"
        )
    with pytest.raises(spec.ConfigurationError):
        control.structure(document, plan=plan, directory=configured)


def test_proxy_budgets_match_actual_single_and_multipart_transfer_routes():
    import re

    from packages.uploads.protocol import MAX_PARTS, PART_SIZE
    from packages.uploads.service import BASE

    raw = (spec.fresh.ROOT / "deploy/nginx-fusion-full.conf").read_text()
    patterns = re.findall(r'location ~ "([^"\n]+)" \{([^}]+)\}', raw)
    upload = "/api/v1/object-transfers/uploads/00000000-0000-4000-8000-000000000001"
    original = next(body for pattern, body in patterns if re.fullmatch(pattern, upload))
    multipart = BASE + "/00000000-0000-4000-8000-000000000001/parts/"
    pattern, body = next(
        (pattern, body) for pattern, body in patterns if re.fullmatch(pattern, multipart + "1")
    )
    assert "client_max_body_size 100m;" in original
    assert "client_max_body_size 8m;" in body and PART_SIZE == 8 * 1024 * 1024
    assert re.fullmatch(pattern, multipart + str(MAX_PARTS))
    assert not re.fullmatch(pattern, multipart + "0")
    assert not re.fullmatch(pattern, multipart + str(MAX_PARTS + 1))
    assert not re.fullmatch(pattern, multipart + "1/more")
    assert "client_max_body_size 5m;" in raw.split("location = /nginx-health")[0]
    assert "access_log off;" in raw.split("location = /nginx-health")[0]
    assert "error_log /dev/null;" in raw.split("location = /nginx-health")[0]
    assert "--no-access-log" in spec.COMMANDS["api"][1]
