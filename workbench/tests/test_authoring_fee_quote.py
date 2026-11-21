"""Exact section authoring fee admission uses the checked local price and never calls a model."""

from contextlib import contextmanager
from contextvars import Context
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api import authoring_fee_routes, task_routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.assistant import budget
from packages.authoring import package_fee_quote as quote
from packages.domain.runtime import DomainError, etag
from packages.tasks import package_authoring_runs, package_runs

BID, TASK, VERSION, PRICE, ACTOR, OTHER_PRICE = (UUID(int=i) for i in range(1, 7))
TASK_PATH = f"/api/v1/bids/{BID}/task-definitions/{TASK}"
VALID_UNTIL = datetime(2040, 1, 1, tzinfo=UTC)
TARIFF = {
    "id": PRICE,
    "version": "synthetic-tariff-v1",
    "provider": "deepseek",
    "model": "deepseek-flash",
    "currency": "CNY",
    "amount_scale": 1000000000,
    "input_hard_ceiling": 999_999,
    "output_hard_ceiling": 4096,
    "input_per_million_minor": 500,
    "output_per_million_minor": 200,
    "valid_until": VALID_UNTIL,
    "source_kind": "explicit_mock_fixture",
    "source_uri": "https://example.invalid/tariff",
    "source_sha256": "a" * 64,
}
# ceil((999999 * 500 + 2048 * 200) / 1000000)
UPPER = 501


def _port(price=TARIFF):
    def execute(sql, params):
        assert "valid_until>clock_timestamp()" in sql
        assert params == (PRICE,)
        return SimpleNamespace(fetchone=lambda: price)

    return SimpleNamespace(execute=execute)


def _template(mode="exact_package_authoring", paused=False):
    return {
        "bid_id": BID,
        "id": TASK,
        "version_id": VERSION,
        "revision": 3,
        "paused": paused,
        "config": {"definition": {"source_selection": {"mode": mode}}},
    }


def test_quote_is_local_and_bound_to_exact_template_and_price(monkeypatch):
    @contextmanager
    def read_transaction():
        def rro(statement):
            assert statement == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"

        yield SimpleNamespace(execute=rro)

    monkeypatch.setattr(authoring_fee_routes, "auth", lambda _request: {"member_id": ACTOR})
    monkeypatch.setattr(authoring_fee_routes, "connection", read_transaction)
    monkeypatch.setattr(
        authoring_fee_routes.templates,
        "current",
        lambda _c, bid, definition: _template() if (bid, definition) == (BID, TASK) else None,
    )
    monkeypatch.setattr(quote.package_job_authority, "require_schema", lambda _c: None)
    marker = object()
    monkeypatch.setattr(quote, "configured", lambda: marker)

    def price(_c, provider):
        assert provider is marker
        return TARIFF

    monkeypatch.setattr(quote.budget, "checked_price", price)
    res = TestClient(app).get(TASK_PATH + "/authoring-fee-quote")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "private,no-store"
    assert res.json() == {
        "protocol": "exact-authoring-fee-quote/1",
        "bid_id": str(BID),
        "definition_id": str(TASK),
        "definition_version_id": str(VERSION),
        "template_etag": etag("task-template", TASK, 3),
        "price_version_id": str(PRICE),
        "currency": "CNY",
        "amount_scale": 1000000000,
        "reserved_minor": UPPER,
        "valid_until": "2040-01-01T00:00:00Z",
        "estimate_not_provider_spend_cap": True,
    }
    actual = implemented_openapi(app)
    path = "/api/v1" + authoring_fee_routes.PATH
    assert actual["paths"][path]["get"]["security"] == [{"SessionCookie": []}]
    post = actual["paths"][path.removesuffix("/authoring-fee-quote") + "/runs"]["post"]
    payload_schema = post["requestBody"]["content"]["application/json"]["schema"]
    assert payload_schema["$ref"] == "#/components/schemas/RunRequest"
    assert "authoring_fee" in actual["components"]["schemas"]["RunRequest"]["properties"]


@pytest.mark.parametrize(
    ("row", "code"),
    (
        (_template("current_project"), "AUTHORING_PACKAGE_QUOTE_UNSUPPORTED"),
        (_template(paused=True), "TASK_TEMPLATE_PAUSED"),
    ),
)
def test_other_or_paused_templates_do_not_read_price(row, code):
    with pytest.raises(DomainError) as error:
        quote.quote(None, row)
    assert error.value.code == code


@pytest.mark.parametrize(
    ("prepared_id", "fee", "price", "code"),
    (
        (OTHER_PRICE, UPPER, TARIFF, "AUTHORING_PACKAGE_PRICE_CHANGED"),
        (PRICE, UPPER, None, "AUTHORING_PACKAGE_PRICE_CHANGED"),
        (PRICE, UPPER - 1, TARIFF, "AUTHORING_PACKAGE_FEE_LIMIT"),
    ),
)
def test_new_authoring_prices_are_guarded_before_jobs_can_be_enqueued(
    monkeypatch, prepared_id, fee, price, code
):
    monkeypatch.setattr(
        budget, "_prepare", lambda *_args, **_kwargs: {"price_version_id": prepared_id}
    )
    with quote.fee_limit(PRICE, fee), pytest.raises(DomainError) as error:
        budget.prepare_package(_port(price), ACTOR, {}, BID, VERSION, "test-input")
    assert error.value.code == code
    # No scope leakage after error. The legacy call still accepts canonical inputs.
    assert budget.prepare_package(None, ACTOR, {}, BID, VERSION, "test-input") == {
        "price_version_id": prepared_id
    }


def test_fee_context_isolated_and_exact_bound_or_reuse_succeeds(monkeypatch):
    with quote.fee_limit(PRICE, UPPER):
        quote.require_admitted_price(_port(), PRICE)
        Context().run(quote.require_admitted_price, None, OTHER_PRICE)
        with quote.fee_limit(OTHER_PRICE, 0):
            with pytest.raises(DomainError, match="价格已更新"):
                quote.require_admitted_price(None, PRICE)
        quote.require_admitted_price(_port(), PRICE)
        monkeypatch.setattr(budget, "_prepare", lambda *_args, **_kwargs: {"reuse_id": TASK})
        # An existing run is never re-priced/recharged.
        assert budget.prepare_package(None, ACTOR, {}, BID, VERSION, "test-input") == {
            "reuse_id": TASK
        }


def test_optional_fee_is_admission_only_and_nonexact_does_not_fall_through(monkeypatch):
    monkeypatch.setattr(task_routes, "auth", lambda *_: {"member_id": ACTOR})
    matches = []

    def run(actor, bid, definition, _key, _condition, body, *, final_auth):
        assert (actor, bid, definition, final_auth()) == (ACTOR, BID, TASK, ACTOR)
        assert body == {"rerun": False}
        matches.append(body)
        return {"status": 202, "body": {"same_exact_task": True}, "headers": {}}, True

    monkeypatch.setattr(package_authoring_runs, "start", run)
    client = TestClient(app)
    approved = {"authoring_fee": {"price_version_id": str(PRICE), "max_reserved_minor": UPPER}}
    with_fee = client.post(TASK_PATH + "/runs", json=approved)
    without_fee = client.post(TASK_PATH + "/runs", json={"rerun": False})
    assert with_fee.status_code == without_fee.status_code == 202
    assert with_fee.json() == without_fee.json() == {"same_exact_task": True}
    assert with_fee.headers["Idempotent-Replayed"] == "true"
    assert len(matches) == 2
    monkeypatch.setattr(package_authoring_runs, "start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        package_runs, "start", lambda *_args, **_kwargs: pytest.fail("must not use generic path")
    )
    wrong = client.post(TASK_PATH + "/runs", json=approved)
    assert (wrong.status_code, wrong.json()["code"]) == (422, "AUTHORING_PACKAGE_QUOTE_UNSUPPORTED")
    invalid = client.post(
        TASK_PATH + "/runs",
        json={"authoring_fee": {"price_version_id": str(PRICE), "max_reserved_minor": "501"}},
    )
    assert (invalid.status_code, invalid.json()["code"]) == (422, "INVALID_REQUEST")


def test_public_new_generation_requires_confirmation_for_non_fixture_price(monkeypatch):
    monkeypatch.setattr(task_routes, "auth", lambda *_: {"member_id": ACTOR})
    monkeypatch.setattr(budget, "_prepare", lambda *_args, **_kwargs: {"price_version_id": PRICE})
    official_test_price = TARIFF | {"source_kind": "official_tariff_and_context_limit"}
    requests = []

    def run(_actor, _bid, _definition, _key, _condition, body, *, final_auth):
        assert final_auth() == ACTOR
        budget.prepare_package(_port(official_test_price), ACTOR, body, BID, VERSION, "fixture")
        requests.append(body)
        return {"status": 202, "body": {"queued_synthetic": True}, "headers": {}}, False

    monkeypatch.setattr(package_authoring_runs, "start", run)
    client = TestClient(app)
    omitted = client.post(TASK_PATH + "/runs", json={"rerun": False})
    assert omitted.status_code == 409
    assert omitted.json()["code"] == "AUTHORING_PACKAGE_FEE_CONFIRMATION_REQUIRED"
    assert not requests
    confirmed = client.post(
        TASK_PATH + "/runs",
        json={"authoring_fee": {"price_version_id": str(PRICE), "max_reserved_minor": UPPER}},
    )
    assert confirmed.status_code == 202
    assert requests == [{"rerun": False}]
