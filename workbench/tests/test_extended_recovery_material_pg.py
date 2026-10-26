"""Native material intent, outbox, send grants, usage and terminal result recovery."""
# ruff: noqa: F401,F811

import os

import httpx
import pytest
from extended_recovery_helpers import BASE, drill, install_remaining
from test_material_execution_dispatch_pg import (
    api,
    exact,
    payload,
    pdf_data,
    ports,
    prepare,
    relay_claim,
    requirements,
    run,
    saved,
    wire,
    world,
)
from test_material_execution_dispatch_pg import database as dispatch_database
from test_package_technical_material import Stream

from deploy import extended_recovery as recovery
from packages.model_governance import material_execution_dispatch as dispatch

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_EXTENDED_RECOVERY_PG") != "1",
    reason="explicit disposable extended recovery PG/S3 required",
)


@pytest.fixture(scope="module")
def database():
    base = dispatch_database.__wrapped__()
    value = next(base)
    try:
        install_remaining(value["owner"], BASE | set(recovery.MATERIAL_SQL))
        yield value
    finally:
        try:
            next(base)
        except StopIteration:
            pass


def test_native_dispatch_ledger_and_private_response_bytes_survive_offline_recovery(
    wire, monkeypatch
):
    lane = prepare(wire, monkeypatch, mode="synthetic_mechanism")
    db = lane["world"]["database"]
    publication = relay_claim(lane)
    assert (
        dispatch.ack_publication(
            db["dispatch_relay"], publication, expected_method_digest=lane["dispatch_method"]
        ).metadata["state"]
        == "published"
    )
    posts = []

    async def handler(request):
        posts.append(request.content)
        return httpx.Response(200, stream=Stream(payload(lane, len(posts) - 1)))

    result = run(lane, mechanism_ports=ports(lane, handler))
    assert (
        result.acknowledge
        and result.observation.metadata["result"]["document"]["state"] == "mechanism_completed"
    )
    assert len(posts) == len(lane["job"].metadata["document"]["slots"])
    drill(
        db,
        "material",
        {
            "technical_material_store.records",
            "material_judgment_job.jobs",
            "material_judgment_job.outbox",
            "material_preparation.leases",
            "material_execution.accounts",
            "material_execution.balances",
            "material_execution.reservations",
            "material_execution.attempts",
            "material_execution.outcomes",
            "material_execution.job_balances",
            "material_dispatch.leases",
            "material_dispatch.states",
            "material_dispatch.results",
        },
        synthetic_original=lane["world"]["io"]["data"],
        extra_login_dsn=db["worker_dsn"],
    )
