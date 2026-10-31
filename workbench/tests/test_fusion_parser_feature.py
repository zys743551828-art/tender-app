"""Synthetic optional parser composition checks; no containers or credentials."""
# ruff: noqa: F401,F811

from copy import deepcopy
from pathlib import Path, PurePosixPath

import pytest
from test_fusion_desktop_compose import plan, request_value, word_request

from deploy import fusion_desktop_compose as desktop
from deploy import fusion_full_runtime as runtime
from deploy import fusion_full_spec as spec
from deploy import fusion_parsing_spec as parsing
from packages.parsing import http_port

IMAGE = "synthetic-parser@sha256:" + "e" * 64


def test_parser_is_explicit_full2_only_and_closed_descriptor(word_request, request_value):
    value = word_request | {"parser": parsing.descriptor(IMAGE)}
    assert desktop.validate_request(value) == value
    with pytest.raises(spec.ConfigurationError):
        desktop.validate_request(request_value | {"parser": value["parser"]})
    for field, bad in [
        ("url", "http://other:8812"),
        ("transport", "arbitrary"),
        ("image", "latest"),
    ]:
        candidate = deepcopy(value)
        candidate["parser"][field] = bad
        with pytest.raises(spec.ConfigurationError):
            desktop.validate_request(candidate)


def test_only_three_clients_join_private_network_and_only_publisher_writes_token(
    word_request, plan, tmp_path
):
    request = word_request | {"parser": parsing.descriptor(IMAGE)}
    current = plan | {"parser": request["parser"]}
    document = desktop.document(request, tmp_path, current)
    assert document["networks"]["parsing"] == {"internal": True}
    services = document["services"]
    assert {
        name for name, service in services.items() if "parsing" in service.get("networks", [])
    } == {"parser", "api", "worker-document", "word-controller"}
    mounts = {
        name: [m for m in service.get("volumes", []) if m.get("source") == "parser_secret"]
        for name, service in services.items()
    }
    assert {name for name, values in mounts.items() if values} == {
        "publish",
        "parser",
        "api",
        "worker-document",
        "word-controller",
    }
    assert mounts["publish"][0]["read_only"] is False
    assert all(
        mounts[name][0]["read_only"]
        for name in ["parser", "api", "worker-document", "word-controller"]
    )
    server = services["parser"]
    assert not server.get("ports") and server["image"] == IMAGE
    assert server["user"] == "65532:65532" and server["read_only"]
    assert server["depends_on"] == {"publish": {"condition": "service_completed_successfully"}}
    assert "parser" not in services["init"]["depends_on"]
    assert not any("PARSING_RUNTIME_TOKEN" == key for key in server["environment"])
    assert "private_config" not in {m.get("source") for m in server["volumes"]}


@pytest.mark.parametrize(
    "component",
    ["api", "document", "word-controller", "export", "comparison", "build-controller", "reconcile"],
)
def test_fixed_components_get_file_transport_without_shared_worker_secret(monkeypatch, component):
    monkeypatch.setattr(spec, "validate_role", lambda profile: None)
    role = spec.COMMANDS[component][0]
    profile = {
        "role": role,
        "environment": {},
        "plan": {
            "parser": parsing.descriptor(IMAGE),
            "model_configured": False,
            "task_runner_enabled": False,
        },
    }
    values = runtime.environment(profile, component)
    if component in parsing.COMPONENTS:
        assert values["PARSING_RUNTIME_URL"] == "http://parser:8812"
        assert values["PARSING_RUNTIME_TOKEN_FILE"] == "/parser-private/token"
        assert "PARSING_RUNTIME_TOKEN" not in values
    else:
        assert not any(key.startswith("PARSING_") for key in values)


@pytest.mark.parametrize(
    "url",
    [
        "http://parser:8812",
        "http://other:8812",
        "https://127.0.0.1:8812",
        "http://127.0.0.1:8812/path",
        "http://user@127.0.0.1:8812",
    ],
)
def test_default_loopback_guard_is_not_broadened(monkeypatch, url):
    monkeypatch.delenv("PARSING_RUNTIME_TRANSPORT", raising=False)
    monkeypatch.setenv("PARSING_RUNTIME_URL", url)
    with pytest.raises(http_port.ParsingUnavailable, match="PARSING_RUNTIME_CONFIG_INVALID"):
        http_port.ParsingHttp()


@pytest.mark.parametrize(
    "url",
    [
        "http://other:8812",
        "http://parser:8813",
        "http://parser:8812/",
        "http://parser:8812?next=evil",
        "https://parser:8812",
        "http://user@parser:8812",
    ],
)
def test_explicit_compose_transport_still_refuses_all_other_urls(monkeypatch, url):
    monkeypatch.setenv("PARSING_RUNTIME_TRANSPORT", "compose-private")
    monkeypatch.setenv("PARSING_RUNTIME_URL", url)
    with pytest.raises(http_port.ParsingUnavailable, match="PARSING_RUNTIME_CONFIG_INVALID"):
        http_port.ParsingHttp()


def test_exact_private_transport_preserves_identity_and_http_client_guards(monkeypatch):
    monkeypatch.setenv("PARSING_RUNTIME_TRANSPORT", "compose-private")
    monkeypatch.setenv("PARSING_RUNTIME_URL", "http://parser:8812")
    monkeypatch.setattr(http_port, "runtime_token", lambda: "synthetic-token-" + "x" * 40)
    identity = {"synthetic": "parser"}
    response = {
        "protocol_version": 1,
        "identity": identity,
        "parser_digest": http_port.digest(identity),
        "config_digest": "f" * 64,
    }
    calls = []

    class Client:
        def __init__(self, **options):
            assert options["trust_env"] is False and options["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request(self, method, url, **options):
            calls.append((method, url, options))
            return http_port.httpx.Response(200, json=response)

    monkeypatch.setattr(http_port.httpx, "Client", Client)
    value = http_port.ParsingHttp()
    assert value.parser_digest == response["parser_digest"]
    assert calls[0][1] == "http://parser:8812/identity"
    response["parser_digest"] = "0" * 64
    with pytest.raises(http_port.ParsingUnavailable, match="PARSING_RUNTIME_IDENTITY_MISMATCH"):
        http_port.ParsingHttp()


@pytest.mark.parametrize("with_parser", [False, True])
def test_every_desktop_source_validator_sees_the_real_readonly_parsing_lock(
    word_request, plan, tmp_path, with_parser
):
    request = word_request
    current = plan
    if with_parser:
        request = request | {"parser": parsing.descriptor(IMAGE)}
        current = current | {"parser": request["parser"]}
    bootstrap = desktop.document(request, tmp_path)
    full = desktop.document(request, tmp_path, current)
    services = {"bootstrap-configure": bootstrap["services"]["configure"]} | full["services"]
    required = {"bootstrap-configure", "configure", "publish", "init", "validation"} | set(
        desktop.full.COMPONENTS
    )
    expected = desktop.bind(
        spec.fresh.ROOT / "requirements-parsing.lock.txt",
        "/workspace/requirements-parsing.lock.txt",
    )
    for name in required:
        mounts = [m for m in services[name]["volumes"] if m["target"] == expected["target"]]
        assert mounts == [expected], name
        assert spec.digest(Path(mounts[0]["source"]).read_bytes()) == spec.digest(
            (spec.fresh.ROOT / "requirements-parsing.lock.txt").read_bytes()
        )
    with pytest.raises(spec.ConfigurationError, match="DESKTOP_SOURCE_WRITABLE"):
        desktop._mount(
            "../requirements-parsing.lock.txt:/workspace/requirements-parsing.lock.txt:rw"
        )


def test_normal_full_template_and_closed_contract_require_parsing_lock(
    request_value, plan, tmp_path
):
    document = desktop._base(request_value, "A" * 22)
    mount = "../requirements-parsing.lock.txt:/workspace/requirements-parsing.lock.txt:ro"
    assert mount in desktop.full.SOURCE_MOUNTS
    for name in {"init"} | set(desktop.full.COMPONENTS):
        assert document["services"][name]["volumes"].count(mount) == 1, name
    desktop.full.structure(document, plan=plan, directory=PurePosixPath(desktop.PRIVATE))
    broken = deepcopy(document)
    broken["services"]["api"]["volumes"].remove(mount)
    with pytest.raises(spec.ConfigurationError, match="FULL_COMPONENT_MOUNT_CHANGED"):
        desktop.full.structure(broken, plan=plan, directory=PurePosixPath(desktop.PRIVATE))


def test_configure_visible_sources_fail_if_required_parsing_lock_is_not_mounted(
    request_value, tmp_path
):
    service = desktop.document(request_value, tmp_path)["services"]["configure"]
    root = tmp_path / "container-visible"
    required = [
        "requirements.lock.txt",
        "requirements-parsing.lock.txt",
        "pyproject.toml",
        "deploy/fusion_full_requirements.txt",
        "deploy/Dockerfile.parsing",
    ]
    for relative in required:
        target = "/workspace/" + relative
        candidates = [
            m
            for m in service["volumes"]
            if target == m["target"] or target.startswith(m["target"].rstrip("/") + "/")
        ]
        mount = max(candidates, key=lambda m: len(m["target"]))
        assert mount["type"] == "bind" and mount["read_only"]
        source = (
            Path(mount["source"]) / target.removeprefix(mount["target"]).lstrip("/")
            if target != mount["target"]
            else Path(mount["source"])
        )
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    assert spec.sources(root)["requirements-parsing.lock.txt"] == spec.digest(
        (spec.fresh.ROOT / "requirements-parsing.lock.txt").read_bytes()
    )
    (root / "requirements-parsing.lock.txt").unlink()
    with pytest.raises(FileNotFoundError):
        spec.sources(root)
