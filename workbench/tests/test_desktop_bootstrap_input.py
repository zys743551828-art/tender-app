"""Bounded bootstrap input and private-stage composition, with synthetic values only."""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import fusion_desktop_compose as desktop
from deploy import fusion_desktop_private as private
from deploy import fusion_full_spec as spec

MODEL = {
    "DEEPSEEK_API_KEY": "synthetic-not-a-real-key",
    "DEEPSEEK_MODEL": "deepseek-flash",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
}


@pytest.mark.parametrize("code", ["NoSuchKey", "credential-shaped-untrusted-code"])
def test_store_stage_diagnostic_exports_only_known_code_and_status(code):
    from botocore.exceptions import ClientError

    error = ClientError(
        {
            "Error": {"Code": code, "Message": "private source, key and signed URL"},
            "ResponseMetadata": {"HTTPStatusCode": 404, "RequestId": "private-request"},
        },
        "GetObject",
    )
    details = private._failure_details(error)
    assert details == {
        "failure_type": "ClientError",
        "store_code": "NoSuchKey" if code == "NoSuchKey" else "UNCLASSIFIED",
        "store_http_status": 404,
        "store_operation": "GetObject",
    }
    encoded = json.dumps(details)
    assert "private" not in encoded and "credential-shaped" not in encoded


PAYLOAD = {"admin_password": "synthetic-bootstrap-password", "model": MODEL}


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("stream", [io.BytesIO, io.StringIO])
def test_read_bootstrap_roundtrip_without_printing(stream, capsys):
    raw = encoded(PAYLOAD)
    supplied = stream(raw if stream is io.BytesIO else raw.decode())
    assert private.read_bootstrap(supplied) == PAYLOAD
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"admin_password":null,"admin_password":null,"model":null}',
        b'{"admin_password":NaN,"model":null}',
        b'{"admin_password":Infinity,"model":null}',
        encoded({"admin_password": None}),
        encoded({"admin_password": None, "model": None, "command": "id"}),
        encoded({"admin_password": None, "model": []}),
    ],
)
def test_strict_json_and_closed_payload_schema(raw):
    with pytest.raises(spec.ConfigurationError):
        private.read_bootstrap(io.BytesIO(raw))


@pytest.mark.parametrize(
    "password",
    ["short", 1, True, "synthetic\npassword", "synthetic\rpassword", "synthetic\x00password"],
)
def test_admin_policy_is_preserved_without_echo(password):
    with pytest.raises(spec.ConfigurationError, match="FULL_ADMIN_PASSWORD_REQUIRED") as error:
        private.read_bootstrap(io.BytesIO(encoded({"admin_password": password, "model": None})))
    assert str(error.value) == "FULL_ADMIN_PASSWORD_REQUIRED"


@pytest.mark.parametrize(
    "model",
    [
        MODEL | {"other": "synthetic"},
        MODEL | {"DEEPSEEK_MODEL": "unsupported"},
        MODEL | {"DEEPSEEK_BASE_URL": "https://other.invalid"},
        MODEL | {"DEEPSEEK_API_KEY": "synthetic\nkey"},
    ],
)
def test_model_uses_existing_closed_spec(model):
    with pytest.raises(spec.ConfigurationError):
        private.read_bootstrap(io.BytesIO(encoded({"admin_password": None, "model": model})))


def test_input_read_is_bounded_in_utf8_bytes():
    class Stream:
        def read(self, limit):
            assert limit == private.MAX_BOOTSTRAP_BYTES + 1
            return b"x" * limit

    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_INPUT_INVALID"):
        private.read_bootstrap(Stream())
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_INPUT_INVALID"):
        private.read_bootstrap(
            io.StringIO(
                json.dumps({"admin_password": "字" * 10000, "model": None}, ensure_ascii=False)
            )
        )


@pytest.fixture
def configuring(tmp_path, monkeypatch):
    from deploy import fusion_full_configure, fusion_full_dependencies

    root = tmp_path / "private"
    root.mkdir()
    public = tmp_path / "public"
    public.mkdir()
    target = root / "deployment"
    request = {
        "version": desktop.VERSION,
        "instance_id": "a" * 32,
        "name": "full_synthetic",
        "origin": "http://127.0.0.1:5189",
        "python_image": "synthetic-python@sha256:" + "b" * 64,
        "web_image": "synthetic-web@sha256:" + "c" * 64,
    }
    (public / "request.json").write_bytes(encoded(request))
    calls = []
    value = {}

    def create(directory, **kwargs):
        calls.append(kwargs)
        directory.mkdir()
        value.update(
            admin_password=kwargs["admin_password"],
            model=kwargs.get("model"),
            plan_digest="d" * 64,
            plan={
                "model_configured": kwargs.get("model") is not None,
                "task_runner_enabled": False,
            },
        )
        (directory / "operator.json").write_bytes(encoded(value))
        (directory / "owner-password").write_bytes(b"synthetic-owner")
        (directory / "s3-identities.json").write_bytes(b"{}")

    monkeypatch.setattr(private, "PRIVATE", target)
    monkeypatch.setattr(private, "PUBLIC", public)
    monkeypatch.setattr(desktop, "validate_request", lambda supplied: request)
    monkeypatch.setattr(fusion_full_configure, "configure", create)
    monkeypatch.setattr(fusion_full_dependencies, "identity", lambda: {})
    monkeypatch.setattr(
        private.secrets, "token_urlsafe", lambda size: "synthetic-random-admin-password"
    )
    monkeypatch.setattr(
        private, "_binding", lambda: (value, {"request": request, "plan_digest": "d" * 64})
    )
    monkeypatch.setattr(private, "_secret", lambda *args: None)
    monkeypatch.setattr(spec, "load_private_json", lambda path: json.loads(path.read_bytes()))
    monkeypatch.setattr(
        spec,
        "write_private",
        lambda path, data: path.write_bytes(data if isinstance(data, bytes) else encoded(data)),
    )
    return target, public, request, value, calls


def test_default_random_path_does_not_add_model_argument(configuring):
    path, public, request, value, calls = configuring
    private.configure()
    private.configure()
    assert len(calls) == 1 and calls[0]["admin_password"] == "synthetic-random-admin-password"
    assert "model" not in calls[0]


def test_operator_password_is_only_used_in_private_create_and_never_reset(configuring):
    path, public, request, value, calls = configuring
    supplied = {"admin_password": PAYLOAD["admin_password"], "model": None}
    assert private.configure(supplied)["private_values_exported"] is False
    private.configure()
    private.configure(supplied)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_BINDING_CHANGED"):
        private.configure(supplied | {"admin_password": "different-synthetic-password"})
    assert len(calls) == 1 and calls[0]["admin_password"] == PAYLOAD["admin_password"]
    assert PAYLOAD["admin_password"].encode() not in (public / "public-plan.json").read_bytes()


def test_declared_model_required_for_new_private_only_and_exact_on_resume(configuring):
    path, public, request, value, calls = configuring
    request["model_configured"] = True
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_MODEL_REQUIRED"):
        private.configure()
    assert not path.exists() and not calls
    private.configure(PAYLOAD)
    private.configure()
    private.configure(PAYLOAD)
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_BINDING_CHANGED"):
        private.configure(PAYLOAD | {"model": MODEL | {"DEEPSEEK_API_KEY": "other-synthetic-key"}})
    assert len(calls) == 1 and calls[0]["model"] == MODEL
    assert MODEL["DEEPSEEK_API_KEY"].encode() not in (public / "public-plan.json").read_bytes()


def test_undeclared_model_payload_never_creates_private(configuring):
    path, public, request, value, calls = configuring
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_BOOTSTRAP_MODEL_INTENT_MISMATCH"):
        private.configure(PAYLOAD)
    assert not path.exists() and not calls


@pytest.mark.parametrize("stage", ["initialize", "publish"])
def test_other_stages_never_read_bootstrap_stdin(stage, monkeypatch, capsys):
    class Forbidden:
        @property
        def buffer(self):
            raise AssertionError("stdin must not be read")

    monkeypatch.setattr(private.sys, "stdin", Forbidden())
    monkeypatch.setattr(private.os, "umask", lambda mask: 0o022)
    monkeypatch.setattr(private, stage, lambda: {"stage": stage})
    assert private.main([stage]) == 0
    assert private.main([stage, "--bootstrap-stdin"]) == 2
    assert "DESKTOP_BOOTSTRAP_STAGE_INVALID" in capsys.readouterr().out


def test_cli_payload_is_not_printed_even_if_configure_raises(monkeypatch, capsys):
    monkeypatch.setattr(private.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(encoded(PAYLOAD))))
    monkeypatch.setattr(private.os, "umask", lambda mask: 0o022)
    captured = []

    def failed(value):
        captured.append(value)
        raise RuntimeError(PAYLOAD["admin_password"] + " " + MODEL["DEEPSEEK_API_KEY"])

    monkeypatch.setattr(private, "configure", failed)
    assert private.main(["configure", "--bootstrap-stdin"]) == 2
    output = capsys.readouterr()
    assert captured == [PAYLOAD]
    assert PAYLOAD["admin_password"] not in output.out + output.err
    assert MODEL["DEEPSEEK_API_KEY"] not in output.out + output.err
    assert "DESKTOP_PRIVATE_STAGE_FAILED" in output.out


@pytest.mark.parametrize("matches", [True, False])
def test_private_binding_checks_model_intent_and_never_allows_task_runner(monkeypatch, matches):
    import deploy

    request = {
        "name": "full_synthetic",
        "origin": "http://127.0.0.1:5189",
        "python_image": "synthetic-python",
        "web_image": "synthetic-web",
        "model_configured": True,
    }
    value = {
        "plan_digest": "d" * 64,
        "plan": {
            "name": request["name"],
            "origin": request["origin"],
            "images": {"python": request["python_image"], "web": request["web_image"]},
            "model_configured": matches,
            "task_runner_enabled": False,
        },
    }
    initialize = SimpleNamespace(operator=lambda path: value)
    monkeypatch.setattr(deploy, "fusion_full_init", initialize, raising=False)
    monkeypatch.setitem(sys.modules, "deploy.fusion_full_init", initialize)
    monkeypatch.setattr(
        spec, "load_private_json", lambda path: {"request": request, "plan_digest": "d" * 64}
    )
    monkeypatch.setattr(desktop, "validate_request", lambda request: request)
    if not matches:
        with pytest.raises(spec.ConfigurationError, match="DESKTOP_PRIVATE_BINDING_CHANGED"):
            private._binding()
    else:
        assert private._binding()[0] is value
        value["plan"]["task_runner_enabled"] = True
        with pytest.raises(spec.ConfigurationError, match="DESKTOP_PRIVATE_BINDING_CHANGED"):
            private._binding()


@pytest.mark.parametrize("enabled", [False, True])
def test_publish_uses_declared_paid_roles_without_changing_word_lane_distribution(
    tmp_path, monkeypatch, enabled
):
    default = ("api", "worker", "relay", "reconcile", "controller")
    roles = default + (("paid_worker", "paid_controller") if enabled else ())
    request = {"version": desktop.VERSION, "model_configured": enabled}
    value = {
        "plan_digest": "d" * 64,
        "plan": {"origin": "http://127.0.0.1:5189"},
        "admin_password": "synthetic-password",
    }
    monkeypatch.setattr(private, "_binding", lambda: (value, {"request": request}))
    monkeypatch.setattr(desktop, "roles", lambda request: roles, raising=False)
    monkeypatch.setattr(
        spec,
        "load_private_json",
        lambda path: {"plan_digest": "d" * 64, "runtime_roles": sorted(roles)},
    )
    monkeypatch.setattr(
        spec,
        "private_file",
        lambda path: encoded({"role": path.parent.name, "plan_digest": "d" * 64}),
    )
    monkeypatch.setattr(spec, "validate_role", lambda profile: None)
    original = Path

    def fixed(path):
        result = tmp_path / str(path).removeprefix("/")
        result.mkdir(exist_ok=True)
        return result

    monkeypatch.setattr(private, "Path", fixed)
    monkeypatch.setattr(private.os, "chown", lambda *args: None, raising=False)
    # This case isolates role distribution; real state ownership/idempotency
    # is covered by test_fusion_desktop_private and the restricted publisher run.
    monkeypatch.setattr(private, "_application_state", lambda state: None)
    writes = []
    monkeypatch.setattr(
        private, "_profile", lambda target, raw: writes.append((target, json.loads(raw)))
    )
    result = private.publish()
    assert result["roles"] == list(roles)
    assert [item[1]["role"] for item in writes[:-1]] == list(roles)
    assert writes[-1][0] == original(tmp_path / "validation-login")
