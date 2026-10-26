"""Package facts must never consume a legacy current-body risk or prediction."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.domain.runtime import DomainError
from packages.metrics import predictions, records, snapshots, views


def package():
    return {
        "id": "00000000-0000-4000-8000-000000000001",
        "bid_id": "00000000-0000-4000-8000-000000000002",
        "subject_kind": "bid_package",
        "body_version_id": None,
        "review_id": None,
        "created_at": datetime(2026, 10, 20, tzinfo=timezone.utc),
        "submitted_at": datetime(2026, 10, 19, tzinfo=timezone.utc),
        "settings": {"show_prediction": True},
        "submission_head_revision": 1,
    }


def test_package_metrics_do_not_borrow_a_successful_legacy_current_review(monkeypatch):
    row = package()
    at = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def execute(statement, _params=None):
        if "package_prediction.submission_pair" in statement:
            return SimpleNamespace(fetchone=lambda: {"ready": False})
        if "clock_timestamp()" in statement:
            return SimpleNamespace(fetchone=lambda: {"t": at})
        if "FROM submission_heads" in statement:
            return SimpleNamespace(fetchall=lambda: [row])
        pytest.fail("Package metric unexpectedly queried the old review: " + statement)

    monkeypatch.setattr(
        views,
        "submission_identity",
        lambda *_args: {
            "status": "confirmed",
            "snapshot": {
                "engineering_project_id": "project",
                "round_id": "round",
                "bidder_id": "bidder",
            },
        },
    )
    monkeypatch.setattr(records, "result_head", lambda *_args, **_kwargs: {"result_id": None})
    monkeypatch.setattr(
        snapshots, "current_risks", lambda *_args: pytest.fail("Borrowed old-body risks")
    )
    value = views.metrics(SimpleNamespace(execute=execute))
    assert value["effective_submissions"] == 1
    assert value["qualification"]["open"] is None
    assert value["qualification"]["open_at_submission"] is None
    assert value["qualification"]["known_current_review_submissions"] == 0
    assert value["qualification"]["unknown_current_review_submissions"] == 1
    assert value["qualification"]["unknown_snapshot_submissions"] == 1
    assert value["online_error"]["prediction_pairs"] == 0
    assert value["online_error"]["excluded_pair_counts"] == {
        "package_prediction_producer_unavailable": 1
    }


def test_registration_gate_cannot_be_frozen_as_a_pre_submission_body_snapshot():
    with pytest.raises(DomainError) as failure:
        snapshots.freeze_submission_risks(
            None, submission=package(), actor="actor", command="command"
        )
    assert failure.value.code == "PACKAGE_RISK_OBSERVATION_REQUIRED"
    assert snapshots.for_submission(None, package()) is None


def test_no_package_prediction_binding_can_be_created_from_legacy_producer_rows():
    assert (
        predictions.bind_submission_prediction(
            None, submission=package(), actor="actor", command="command"
        )
        is None
    )
    pairs, excluded = predictions.eligible_pairs(
        SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: {"ready": False})),
        [package()],
        as_of=datetime.now(timezone.utc),
    )
    assert not pairs and excluded == {"package_prediction_producer_unavailable": 1}


def test_legacy_risk_projection_still_uses_the_original_scope(monkeypatch):
    expected = {"available": True, "open": 3}
    monkeypatch.setattr(
        snapshots,
        "current_risks",
        lambda c, bid: expected if (c, bid) == ("connection", "bid") else None,
    )
    assert snapshots.for_current_submission("connection", {"bid_id": "bid"}) == expected
