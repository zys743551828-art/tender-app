"""Real application/adapters with inert object I/O and explicit transaction observations."""

import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from packages.domain.errors import DomainError
from packages.model_registration import infrastructure as infra
from packages.model_registration.application import ModelRegistration, Register


@pytest.fixture
def world(monkeypatch):
    events = []
    state = {"depth": 0, "early": False, "late": False, "drift": False, "stage_error": None}
    saved = {"body": {"model": "saved"}, "status": 201, "headers": {"ETag": "result"}}

    class C:
        def execute(self, sql, params):
            assert state["depth"] == 1 and sql.startswith("SELECT response FROM commands")
            events.append("lookup")
            return SimpleNamespace(fetchone=lambda: {"response": saved} if state["early"] else None)

    @contextmanager
    def connect():
        state["depth"] += 1
        events.append("begin")
        try:
            yield C()
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise
        finally:
            state["depth"] -= 1

    def preview(c, identity):
        events.append("preview")
        return {"document": {"frozen": True}}, "changed" if state[
            "drift"
        ] and "stage" in events else "original"

    def stage(document):
        assert state["depth"] == 0 and document == {"frozen": True}
        events.append("stage")
        if state["stage_error"]:
            raise state["stage_error"]
        return {"raw": b"inert"}

    def publish(c, **kwargs):
        assert state["depth"] == 1 and kwargs["condition"] == "original"
        events.append("publish")
        return {"model": "saved"}, "result"

    class Command:
        def __init__(self, c, *args):
            events.append("command")
            self.id = "command"
            self.replay = saved if state["early"] or state["late"] else None

        def finish(self, body, status, headers):
            events.append("finish")
            return {"body": body, "status": status, "headers": headers}

    monkeypatch.setattr(infra, "Command", Command)
    monkeypatch.setattr(infra.registry, "preview", preview)
    monkeypatch.setattr(infra.registry, "stage", stage)
    monkeypatch.setattr(infra.registry, "publish", publish)
    service = ModelRegistration(infra.SqlTransactions(connect), infra.RegistryObjects())
    request = Register(
        "member",
        UUID("00000000-0000-4000-8000-000000000001"),
        "reason",
        {"reason": "reason"},
        "original",
        "key",
    )
    return SimpleNamespace(
        events=events, state=state, saved=saved, service=service, request=request
    )


def test_registration_preserves_preview_command_order_and_no_io_under_lock(world):
    result = world.service.register(world.request)
    assert result.result == world.saved and not result.replayed
    assert world.events == [
        "begin",
        "preview",
        "lookup",
        "commit",
        "stage",
        "begin",
        "preview",
        "command",
        "publish",
        "finish",
        "commit",
    ]
    assert world.state["depth"] == 0


def test_initial_replay_still_validates_source_but_never_stages(world):
    world.state["early"] = True
    assert world.service.register(world.request).replayed
    assert world.events == ["begin", "preview", "lookup", "command", "commit"]


def test_concurrent_replay_after_staging_never_publishes_again(world):
    world.state["late"] = True
    assert world.service.register(world.request).replayed
    assert "stage" in world.events and "publish" not in world.events
    assert world.state["depth"] == 0


def test_source_drift_rolls_back_before_command_finish(world):
    world.state["drift"] = True
    with pytest.raises(DomainError):
        world.service.register(world.request)
    assert world.events[-1] == "rollback" and "finish" not in world.events
    assert world.state["depth"] == 0


class Cancelled(BaseException):
    pass


@pytest.mark.parametrize("error", [RuntimeError("private object diagnostic"), Cancelled()])
def test_failed_or_cancelled_object_io_has_no_open_connection_or_publication(world, error):
    world.state["stage_error"] = error
    with pytest.raises(type(error)):
        world.service.register(world.request)
    assert world.events[-1] == "stage" and world.state["depth"] == 0
    assert "publish" not in world.events


def test_model_read_verifies_bytes_between_short_transactions(world, monkeypatch):
    monkeypatch.setattr(infra.registry, "blob", lambda c, i: {"id": i})

    def read(stored):
        assert world.state["depth"] == 0
        world.events.append("verify")

    monkeypatch.setattr(infra.registry, "read", read)
    monkeypatch.setattr(infra.registry, "view", lambda c, i: ({"current": True}, "current-tag"))
    assert world.service.read(world.request.training_job_id) == ({"current": True}, "current-tag")
    assert world.events == ["begin", "commit", "verify", "begin", "commit"]


def test_registration_application_has_no_framework_storage_or_sql_imports():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / "packages/model_registration/application.py").read_text())
    actual = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert actual <= {"contextlib", "dataclasses", "typing", "uuid"}
    assert not any(isinstance(n, ast.Import) for n in ast.walk(tree))
    routes = ast.parse((root / "apps/api/model_registry_routes.py").read_text())
    for node in routes.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"register_model", "get_model"}:
            calls = [ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)]
            assert not any(
                n == "connection" or n.startswith("registry.") or n.endswith(".execute")
                for n in calls
            )
