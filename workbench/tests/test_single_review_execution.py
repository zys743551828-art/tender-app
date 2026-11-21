"""A native plan can disable paid review while an unrelated assistant has credentials."""

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api import review_routes, review_views, views
from packages.domain import reviews, word_materials
from packages.domain.runtime import DomainError


def test_automatic_intent_is_recorded_and_project_explains_why_it_waits(monkeypatch):
    monkeypatch.setenv("WORKBENCH_SINGLE_REVIEW_CONFIGURED", "0")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-assistant-only")
    bid, command, body = uuid4(), uuid4(), uuid4()
    row = {
        "id": bid,
        "settings": {"auto_review": True},
        "current_body_id": body,
        "current_material_id": uuid4(),
        "current_review_id": None,
        "material_revision": 2,
        "title": "synthetic",
        "revision": 3,
        "presentation_revision": 1,
        "phase": "working",
        "archived_at": None,
        "stream_id": uuid4(),
    }
    connection = SimpleNamespace(
        execute=lambda *_: SimpleNamespace(
            fetchone=lambda: {"pending_intent": {"state": "preparing"}}
        )
    )
    monkeypatch.setattr(reviews, "_locked", lambda *_: (row, {}))
    calls = []
    monkeypatch.setattr(
        reviews, "queue_intent", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    reviews.on_material_commit(connection, bid, command)
    ((args, kwargs),) = calls
    assert args[1:] == (
        bid,
        command,
        {"body_version_id": str(body), "material_revision": 2, "trigger": "automatic"},
    )
    assert kwargs == {"automatic": True}
    monkeypatch.setattr(views, "fetch", lambda *_: row)
    monkeypatch.setattr(word_materials, "pending_body", lambda *_: None)
    monkeypatch.setattr(views, "identity_snapshot", lambda *_: {})
    action = views.bid_view(connection, bid)["next_action"]
    assert action["blocked"] and action["target_url"] == f"/bids/{bid}/review"
    assert "单稿评审请求已记录" in action["reason"] and "未启用" in action["reason"]


@pytest.mark.parametrize("declared,expected", [("0", False), ("1", True), (None, None)])
def test_state_reports_the_review_plan_without_changing_recorded_intent(
    monkeypatch, declared, expected
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-assistant-only")
    if declared is None:
        monkeypatch.delenv("WORKBENCH_SINGLE_REVIEW_CONFIGURED", raising=False)
    else:
        monkeypatch.setenv("WORKBENCH_SINGLE_REVIEW_CONFIGURED", declared)
    intent = {"request_id": str(uuid4()), "state": "preparing", "trigger": "automatic"}
    row = dict(
        material_revision=2,
        current_body_id=uuid4(),
        current_material_id=uuid4(),
        current_rule_set_id=None,
        current_review_id=None,
        revision=3,
        pending_intent=intent,
    )
    monkeypatch.setattr(review_views, "fetch", lambda *_: row)
    state = review_views.review_state(None, uuid4())
    assert state.get("review_execution_configured") is expected
    if expected is None:
        assert "review_execution_configured" not in state
    assert state["request"]["request_id"] == intent["request_id"]
    assert state["request"]["state"] == "preparing"
    assert state["request"]["trigger"] == "automatic"


@pytest.mark.parametrize("replayed", [False, True])
def test_manual_request_preserves_prior_receipt_and_rejects_new_work_when_disabled(
    monkeypatch, replayed
):
    monkeypatch.setenv("WORKBENCH_SINGLE_REVIEW_CONFIGURED", "0")
    monkeypatch.setattr(review_routes, "auth", lambda *_: {"member_id": uuid4()})
    monkeypatch.setattr(review_routes, "validate", lambda *_: None)
    monkeypatch.setattr(review_routes, "connection", lambda: nullcontext(None))
    stored = {"body": {"resource_id": str(uuid4())}, "status": 202, "headers": {}}
    monkeypatch.setattr(
        review_routes,
        "begin",
        lambda *_, **__: SimpleNamespace(replay=stored if replayed else None),
    )
    monkeypatch.setattr(
        review_routes.DeepSeekClient,
        "from_env",
        lambda: pytest.fail("provider config was accessed"),
    )
    monkeypatch.setattr(
        review_routes, "queue_intent", lambda *_: pytest.fail("unexpected new review")
    )
    request = SimpleNamespace(headers={"idempotency-key": str(uuid4())})
    if replayed:
        response = review_routes.request_review(uuid4(), request, {})
        assert response.status_code == 202 and response.headers["Idempotent-Replayed"] == "true"
        assert stored["body"]["resource_id"].encode() in response.body
    else:
        with pytest.raises(DomainError, match="当前部署未启用") as failure:
            review_routes.request_review(uuid4(), request, {})
        assert failure.value.code == "REVIEW_EXECUTION_NOT_CONFIGURED"
