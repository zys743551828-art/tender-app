# ruff: noqa: F811 -- pytest shared fixture injection
"""Actual CPU route exercises over a simulated native channel, never native acceptance."""

import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from test_package_feature_training_io import cohort  # noqa: F401 -- actual /3 private CAS
from test_package_model_observation import material  # noqa: F401 -- actual CAS material
from test_package_model_registry import source

from packages.domain.review_identity import canonical, digest
from packages.model_governance.common import GovernanceError
from packages.package_model_observation import execution
from packages.package_model_registry import artifact
from packages.package_model_route import application


def model(intercept):
    packet = source()
    packet["candidate"]["model"]["intercept"] = str(intercept)
    packet["candidate"]["model_digest"] = digest(packet["candidate"]["model"])
    packet["candidate_digest"] = digest(packet["candidate"])
    return artifact.build(packet)


class NativeChannel:
    """Simulated nonowner authority to test consumers, not SQL concurrency proof."""

    def __init__(self, fixture):
        self.root, self.index, base, self.observation_request = fixture
        self.candidate, self.fallback = model(15), model(75)
        self.sources = {
            doc["model_id"]: dict(deepcopy(base), document=doc)
            for doc in (self.candidate, self.fallback)
        }
        self.routes, self.events, self.revoked = {}, {}, set()
        self.active = False
        self.computed = []
        self.before_commit = None
        self.lose_ack = False

    @contextmanager
    def transactions(self):
        assert not self.active
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    def replay(self, actor, body):
        if actor != "owner":
            raise PermissionError()
        if body["command_id"] in self.events:
            command, receipt = self.events[body["command_id"]]
            if command != body:
                raise ValueError("command conflict")
            return deepcopy(receipt)
        return None

    def prepare(self, actor, body):
        self.replay(actor, body)
        old = self.routes.get(body["route_id"])
        if body["action"] == "activate":
            if old or body["expected_revision"] != 0:
                raise ValueError("revision")
            config = body["config"]
            selected = config["candidate_model_id"]
            if config["fallback_model_id"] in self.revoked:
                raise ValueError("fallback revoked")
        else:
            if not old or old["revision"] != body["expected_revision"]:
                raise ValueError("revision")
            config = old["config"]
            if body["action"] == "rollback":
                if old["rolled_back"]:
                    raise ValueError("already rolled back")
                selected = config["fallback_model_id"]
            else:
                selected = old["selected_model_id"]
        if selected in self.revoked:
            raise ValueError("selected source revoked")
        return {
            "source": deepcopy(self.sources[selected]),
            "observation_request": {
                "version": "package-internal-observation-request/1",
                "command_id": str(
                    uuid5(UUID(body["command_id"]), "package-internal-route-observation/1")
                ),
                "model_id": selected,
                "admission_id": config["admission_id"],
                "artifact_digest": config["candidate_artifact_digest"]
                if selected == config["candidate_model_id"]
                else config["fallback_artifact_digest"],
                "method_digest": config["observation_method_digest"],
                "reference": config["reference"],
            },
            "config": config,
            "selected_model_id": selected,
            "previous_model_id": old["selected_model_id"] if old else None,
            "revision": body["expected_revision"] + 1,
            "rolled_back": body["action"] == "rollback" or bool(old and old["rolled_back"]),
        }

    def commit(self, actor, body, pinned, result):
        if self.before_commit:
            callback, self.before_commit = self.before_commit, None
            callback()
        if previous := self.replay(actor, body):
            return previous
        packet = self.prepare(actor, body)
        if (
            digest(packet) != pinned
            or result["request_digest"] != digest(packet["observation_request"])
            or result["source_digest"] != digest(packet["source"])
            or result["model_id"] != packet["selected_model_id"]
        ):
            raise ValueError("fence/source/result mismatch")
        receipt = {
            "action": body["action"],
            "revision": packet["revision"],
            "selected_model_id": packet["selected_model_id"],
            "previous_model_id": packet["previous_model_id"],
            "result_digest": digest(result),
            "business_route_changed": False,
            "formal_eligibility": "unavailable",
            "historical_receipt": True,
        }
        self.routes[body["route_id"]] = deepcopy(packet)
        self.events[body["command_id"]] = deepcopy(body), deepcopy(receipt)
        if self.lose_ack:
            self.lose_ack = False
            raise ConnectionError("ack lost after commit")
        return receipt

    def execute(self, packet, request):
        assert not self.active
        result = execution.LocalExecutor(self.root, self.index)(packet, request)
        self.computed.append(result)
        return result

    def service(self):
        return application.Routes(self.transactions, self.execute)

    def activate(self):
        return {
            "version": application.VERSION,
            "command_id": str(uuid4()),
            "route_id": str(uuid4()),
            "action": "activate",
            "expected_revision": 0,
            "method_digest": application.method_digest(),
            "config": {
                "candidate_model_id": self.candidate["model_id"],
                "candidate_artifact_digest": digest(self.candidate),
                "fallback_model_id": self.fallback["model_id"],
                "fallback_artifact_digest": digest(self.fallback),
                "admission_id": self.observation_request["admission_id"],
                "reference": self.observation_request["reference"],
                "observation_method_digest": execution.method_digest(),
            },
        }


def action(activated, name, revision):
    return {k: v for k, v in activated.items() if k != "config"} | {
        "command_id": str(uuid4()),
        "action": name,
        "expected_revision": revision,
    }


def test_actual_route_switch_post_rollback_selection_and_no_business_output(material):  # noqa: F811
    native = NativeChannel(material)
    service, activate = native.service(), native.activate()
    first = service.execute("owner", activate)
    rollback = action(activate, "rollback", 1)
    second = service.execute("owner", rollback)
    third = service.execute("owner", action(activate, "consume", 2))
    assert first["selected_model_id"] == native.candidate["model_id"]
    assert second["previous_model_id"] == native.candidate["model_id"]
    assert second["selected_model_id"] == third["selected_model_id"] == native.fallback["model_id"]
    assert native.computed[0]["value"] != native.computed[1]["value"]
    assert native.computed[1]["value"] == native.computed[2]["value"]
    assert len(native.events) == 3 and third["revision"] == 3
    assert not third["business_route_changed"] and third["formal_eligibility"] == "unavailable"
    assert "value" not in third
    with pytest.raises(ValueError):
        service.execute("owner", action(activate, "rollback", 3))
    with pytest.raises(ValueError):
        service.execute("owner", activate | {"command_id": str(uuid4())})


def test_duplicate_lost_ack_and_historical_receipt_after_revocation(material):  # noqa: F811
    native = NativeChannel(material)
    service, activate = native.service(), native.activate()
    service.execute("owner", activate)
    rollback = action(activate, "rollback", 1)
    native.lose_ack = True
    with pytest.raises(ConnectionError):
        service.execute("owner", rollback)
    native.revoked.add(native.fallback["model_id"])
    recovered = service.execute("owner", rollback)
    assert recovered["revision"] == 2 and len(native.computed) == 2
    assert service.execute("owner", rollback) == recovered
    with pytest.raises(ValueError):
        service.execute("owner", action(activate, "consume", 2))
    with pytest.raises(PermissionError):
        service.execute("other", rollback)
    with pytest.raises(ValueError):
        service.execute("owner", rollback | {"expected_revision": 2})


def test_revoked_candidate_can_rollback_but_revoked_target_cannot(material):  # noqa: F811
    native = NativeChannel(material)
    service, activate = native.service(), native.activate()
    service.execute("owner", activate)
    native.revoked.add(native.candidate["model_id"])
    with pytest.raises(ValueError):
        service.execute("owner", action(activate, "consume", 1))
    assert (
        service.execute("owner", action(activate, "rollback", 1))["selected_model_id"]
        == native.fallback["model_id"]
    )


@pytest.mark.parametrize(
    "attack", ["revision", "revoke", "source_drift", "failure", "cancel", "tamper"]
)
def test_failed_or_stale_rollback_never_switches_route(material, attack):  # noqa: F811
    native = NativeChannel(material)
    service, activate = native.service(), native.activate()
    service.execute("owner", activate)
    before = deepcopy(native.routes)
    if attack == "revision":

        def conflict():
            native.routes[activate["route_id"]]["revision"] += 1

        native.before_commit = conflict
    elif attack == "revoke":
        native.before_commit = lambda: native.revoked.add(native.fallback["model_id"])
    elif attack == "source_drift":
        native.before_commit = lambda: native.sources[native.fallback["model_id"]].update(
            closure=["changed"]
        )
    else:

        def broken(packet, request):
            if attack == "failure":
                raise ValueError("CPU")
            if attack == "cancel":
                raise KeyboardInterrupt()
            return native.execute(packet, request) | {"model_id": native.candidate["model_id"]}

        service.executor = broken
    with pytest.raises((ValueError, KeyboardInterrupt)):
        service.execute("owner", action(activate, "rollback", 1))
    stored = native.routes[activate["route_id"]]
    assert stored["selected_model_id"] == native.candidate["model_id"] and not stored["rolled_back"]
    assert len(native.events) == 1 and not native.active
    if attack != "revision":
        assert native.routes == before


@pytest.mark.parametrize("field", ["target_model_id", "verified", "result", "config"])
def test_consumer_cannot_override_fixed_target(material, field):  # noqa: F811
    native = NativeChannel(material)
    activate = native.activate()
    request = action(activate, "rollback", 1) | {field: "forged"}
    with pytest.raises(GovernanceError):
        native.service().execute("owner", request)
    assert not native.computed and not native.routes


@pytest.mark.parametrize("attack", ["same_target", "method", "bool_revision", "version"])
def test_closed_versioned_commands(material, attack):  # noqa: F811
    native = NativeChannel(material)
    request = native.activate()
    if attack == "same_target":
        request["config"]["fallback_model_id"] = request["config"]["candidate_model_id"]
    elif attack == "method":
        request["method_digest"] = "a" * 64
    elif attack == "bool_revision":
        request["expected_revision"] = False
    else:
        request["version"] = "model-release/1"
    with pytest.raises(GovernanceError):
        native.service().execute("owner", request)
    assert not native.computed and not native.routes


def test_cli_wires_real_application_and_has_no_result_ingest(
    monkeypatch, tmp_path, capsys, material
):  # noqa: F811
    from deploy import package_model_route as cli
    from packages.package_model_route.infrastructure import NativeTransactions

    native = NativeChannel(material)
    body = native.activate()
    path = tmp_path / "request"
    path.write_bytes(canonical(body))
    path.chmod(0o600)
    calls = []

    def execute(self, actor, request):
        assert isinstance(self.transactions, NativeTransactions)
        assert isinstance(self.executor, execution.LocalExecutor)
        calls.append(request)
        return {"business_route_changed": False}

    monkeypatch.setattr(application.Routes, "execute", execute)
    monkeypatch.setattr(
        "sys.argv",
        [
            "route",
            "--actor",
            str(uuid4()),
            "--request",
            str(path),
            "--expected-request-digest",
            digest(body),
            "--store",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path),
        ],
    )
    assert cli.main() == 0 and calls == [body]
    assert "false" in capsys.readouterr().out
    path.chmod(0o644)
    assert cli.main() == 2 and len(calls) == 1
    output = capsys.readouterr()
    assert str(path) not in output.out and not output.err


def test_sql_and_architecture_keep_business_routes_and_observation_method_untouched():
    root = Path(__file__).parents[1]
    sql = (root / "deploy/sql/package-model-route.sql").read_text()
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "old.actor_id IS DISTINCT FROM actor" in sql
    assert "old.revision<>expected" in sql and "old.rolled_back" in sql
    assert "lock_scope(members||" in sql
    assert sql.index("lock_scope(members||") < sql.index(
        "snapshot:=package_model_observation.source"
    )
    assert "packet:=package_model_route.prepare(actor,body)" in sql
    assert "design.package_technical_digest(packet) IS DISTINCT FROM pinned" in sql
    assert "observation:=package_model_observation.record" in sql
    assert sql.index("observation:=package_model_observation.record") < sql.index(
        "UPDATE package_model_route.routes"
    )
    assert "UNIQUE(route_id,revision)" in sql
    assert "GRANT SELECT" not in sql and "GRANT INSERT" not in sql
    for target in ("design.model_routes", "model_release.routes", "certifications"):
        assert target not in sql
    tree = ast.parse((root / "packages/package_model_route/application.py").read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(
        name
        and any(
            part in name for part in ("psycopg", "fastapi", "infrastructure", "platform_runtime")
        )
        for name in imports
    )


def test_interleaved_competing_consume_fences_rollback_without_partial_event(material):
    native = NativeChannel(material)
    activate = native.activate()
    native.service().execute("owner", activate)
    competing = action(activate, "consume", 1)

    def execute(packet, request):
        result = native.execute(packet, request)
        native.service().execute("owner", competing)
        return result

    service = application.Routes(native.transactions, execute)
    with pytest.raises(ValueError):
        service.execute("owner", action(activate, "rollback", 1))
    route = native.routes[activate["route_id"]]
    assert route["revision"] == 2 and route["selected_model_id"] == native.candidate["model_id"]
    assert len(native.events) == 2 and not route["rolled_back"]


def test_interleaved_duplicate_commits_once_and_recovers_first_result(material):
    native = NativeChannel(material)
    activate = native.activate()
    native.service().execute("owner", activate)
    rollback = action(activate, "rollback", 1)
    first = []

    def execute(packet, request):
        result = native.execute(packet, request)
        first.append(native.service().execute("owner", rollback))
        return result

    receipt = application.Routes(native.transactions, execute).execute("owner", rollback)
    assert receipt == first[0] and receipt["revision"] == 2
    assert len(native.events) == 2
    assert native.routes[activate["route_id"]]["selected_model_id"] == native.fallback["model_id"]
