"""Behavioral transaction boundaries, independent of HTTP/SQL/provider fixtures."""

from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from packages.domain.errors import DomainError
from packages.material_jobs.application import MaterialJobs, Target

TARGET = Target(("bid", "package", "revision"), "scope", "member")


@dataclass
class World:
    active: int = 0
    accepted: bool = False
    fail_commit: bool = False
    fail_authorize: Exception | None = None
    concurrent_acceptance: bool = False
    submissions: int = 0
    transactions: int = 0

    @contextmanager
    def transaction(self, readonly=False):
        self.active += 1
        self.transactions += 1
        try:
            yield Tx(self, readonly)
            if self.fail_commit:
                raise RuntimeError("commit failed")
        finally:
            self.active -= 1

    def submit(self, command):
        assert self.active == 0 and command == {"command_id": "fixed"}
        self.submissions += 1
        self.accepted = True
        return "unconfirmed"  # Native commit followed by lost acknowledgement.

    def service(self):
        return MaterialJobs(self.transaction, self.submit)


@dataclass
class Tx:
    world: World
    readonly: bool

    def prepare(self, target, body, condition, key):
        assert self.world.active == 1 and not self.readonly
        assert target == TARGET and (body, condition, key) == ({"fixed": True}, "etag", "key")
        return "intent"

    def observe(self, target, identity, reason="NATIVE_ACCEPTANCE_PENDING"):
        assert target == TARGET and identity == "intent"
        return {"job": {"id": "native"} if self.world.accepted else None, "reason": reason}

    def authorize(self, target, identity):
        if self.world.fail_authorize:
            self.world.accepted = self.world.concurrent_acceptance
            raise self.world.fail_authorize
        return {"command_id": "fixed"}

    def execution_state(self, target, identity):
        assert self.readonly and self.world.active == 1
        return {"fee_state": "unknown", "final_fee_minor": None}


def test_commit_before_submit_and_lost_ack_recovers_by_native_observation():
    world = World()
    service = world.service()
    result = service.request(TARGET, {"fixed": True}, "etag", "key")
    assert result["job"] == {"id": "native"}
    assert world.transactions == 3 and world.active == 0 and world.submissions == 1
    assert service.resume(TARGET, "intent")["job"] == result["job"]
    assert world.submissions == 1


def test_commit_failure_never_calls_native_channel():
    world = World(fail_commit=True)
    with pytest.raises(RuntimeError, match="commit failed"):
        world.service().request(TARGET, {"fixed": True}, "etag", "key")
    assert world.active == 0 and world.submissions == 0


@pytest.mark.parametrize("accepted", [False, True])
def test_authority_failure_reobserves_concurrent_acceptance_without_send(accepted):
    world = World(fail_authorize=DomainError("REVOKED", "revoked"), concurrent_acceptance=accepted)
    result = world.service().resume(TARGET, "intent")
    assert bool(result["job"]) is accepted and result["reason"] == "REVOKED"
    assert world.submissions == 0 and world.active == 0


def test_unexpected_adapter_error_is_not_disguised_as_domain_refusal():
    world = World(fail_authorize=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        world.service().resume(TARGET, "intent")
    assert world.active == 0 and world.submissions == 0


def test_read_and_fee_observation_never_authorize_or_submit():
    world = World(fail_authorize=AssertionError("must not authorize historical reads"))
    assert world.service().read(TARGET, "intent")["job"] is None
    assert world.service().execution_state(TARGET, "intent") == {
        "fee_state": "unknown",
        "final_fee_minor": None,
    }
    assert world.submissions == 0 and world.active == 0


def test_native_exception_leaves_no_open_transaction():
    world = World()

    def lost(command):
        assert world.active == 0
        raise RuntimeError("transport unavailable")

    service = MaterialJobs(world.transaction, lost)
    with pytest.raises(RuntimeError, match="transport unavailable"):
        service.resume(TARGET, "intent")
    assert world.active == 0
