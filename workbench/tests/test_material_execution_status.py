"""Read-only synthetic authority projection, including late settlement and isolation."""

# ruff: noqa: F401,F811
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_material_qualified_jobs import world

from apps.api import package_technical_execution as routes
from packages.domain.errors import DomainError
from packages.model_governance import material_execution_status as status
from packages.model_governance import material_qualified_jobs as q


@pytest.fixture
def lane(world):
    identity = world["prepare"]()
    receipt = world["resume"](identity)
    row = world["intents"][identity]
    state = dict(
        intent_id=identity,
        actor_id=row["actor_id"],
        scope_id=row["scope_id"],
        bid_id=row["bid_id"],
        job_id=receipt["job"]["job_id"],
        job_digest=receipt["job"]["job_digest"],
        qualification_state="approved",
        execution_state="in_flight",
        execution_mode="isolated_synthetic_mechanism",
        currency="USD",
        reserved_minor=100,
        held_minor=100,
        known_estimated_minor=0,
        released_minor=0,
        attempt_count=1,
        unsettled_count=1,
        unknown_count=0,
        last_settled_at=None,
        observed_at=datetime.now(timezone.utc),
    )

    class C:
        available = True

        def execute(self, sql, params=None):
            if sql.startswith("SET TRANSACTION"):
                value = None
            elif "to_regclass" in sql:
                value = {"relation": "view" if self.available else None}
            elif "execution_status WHERE" in sql:
                assert tuple(map(str, params)) == (
                    identity,
                    row["actor_id"],
                    row["scope_id"],
                    row["bid_id"],
                )
                value = state
            elif "acceptances WHERE" in sql:
                value = world["accepted"][identity]
            elif "intents WHERE" in sql:
                value = row if params[2] == row["actor_id"] else None
            else:
                raise AssertionError(sql)
            return SimpleNamespace(fetchone=lambda: deepcopy(value))

    return SimpleNamespace(c=C(), state=state, row=row, world=world)


def test_unknown_is_not_zero_and_revocation_does_not_hide_late_settlement(lane):
    first = status.observe(lane.c, lane.row)
    assert first["fee_state"] == "in_flight" and first["final_fee_minor"] is None
    lane.state.update(
        execution_state="unknown", qualification_state="revoked", unsettled_count=0, unknown_count=1
    )
    second = status.observe(lane.c, lane.row)
    assert (
        second["fee_state"] == "unknown"
        and second["known_estimated_minor"] == 0
        and second["final_fee_minor"] is None
    )


def test_revoked_inflight_job_can_read_late_settlement(lane):
    # The existing immutable unknown outcome is never rewritten by this API.
    lane.state.update(qualification_state="revoked", unsettled_count=0)
    lane.state.update(
        execution_state="completed",
        unknown_count=0,
        held_minor=0,
        known_estimated_minor=24,
        released_minor=76,
        last_settled_at=datetime.now(timezone.utc),
    )
    third = status.observe(lane.c, lane.row)
    assert third["fee_state"] == "settled_estimate" and third["qualification_state"] == "revoked"
    assert (
        third["known_estimated_minor"] == 24
        and not third["send_authorized"]
        and not third["invoice_reconciled"]
    )


def test_missing_projection_is_explicit_without_numeric_fees(lane):
    lane.c.available = False
    value = status.observe(lane.c, lane.row)
    assert value["available"] is False and "known_estimated_minor" not in value


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": "wrong"},
        {"job_digest": "0" * 64},
        {"held_minor": -1},
        {"known_estimated_minor": True},
        {"currency": "bad"},
        {"execution_state": "fake_success"},
        {"unknown_count": 2},
        {"qualification_state": "verified"},
        {"execution_state": None},
    ],
)
def test_bad_projection_is_never_displayed_as_success(lane, change):
    lane.state.update(change)
    with pytest.raises(DomainError):
        status.observe(lane.c, lane.row)


def test_unstarted_ledger_is_absent_not_zero(lane):
    lane.state.update(
        execution_state=None,
        execution_mode=None,
        currency=None,
        reserved_minor=None,
        held_minor=None,
        known_estimated_minor=None,
        released_minor=None,
        attempt_count=0,
        unsettled_count=0,
    )
    value = status.observe(lane.c, lane.row)
    assert value["fee_state"] == "not_started" and value["known_estimated_minor"] is None


def test_route_snapshot_auth_private_read_and_cross_member_rejection(lane, monkeypatch):
    @contextmanager
    def connect():
        yield lane.c

    monkeypatch.setattr(routes, "connection", connect)
    monkeypatch.setattr(routes, "auth", lambda r: {"member_id": lane.row["actor_id"]})
    args = dict(
        bid_id=UUID(lane.row["bid_id"]),
        package_id=UUID(lane.row["bid_id"]),
        revision_id=UUID(lane.row["bid_id"]),
        scope_id=UUID(lane.row["scope_id"]),
        intent_id=UUID(lane.row["id"]),
        r=None,
    )
    result = routes.qualified_execution_state(**args)
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    monkeypatch.setattr(routes, "auth", lambda r: {"member_id": "other-member"})
    with pytest.raises(DomainError):
        routes.qualified_execution_state(**args)
