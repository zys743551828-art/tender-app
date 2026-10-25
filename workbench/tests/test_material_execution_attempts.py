"""Original full serializer/HTTP codec, once-only runtime and financial outcomes."""

# ruff: noqa: F401,F811
import asyncio
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from test_material_request_preflight import idle_connection, owned, synthetic, uid
from test_package_material_cost import policy_data
from test_package_technical_material import Stream, judgment, response

from packages.domain.providers.deepseek_vision import VisionProviderError, parse_response
from packages.domain.review_identity import digest
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material


def envelope(document):
    return {"document": deepcopy(document), "digest": digest(document)}


def sample(owned, checked):
    now = datetime.now(timezone.utc)
    request = checked.metadata["requests"][0]
    d = {
        "version": "material-execution-attempt/1",
        "attempt_id": uid(301),
        "command_id": uid(302),
        "job_id": checked.metadata["job_id"],
        "slot_id": uid(303),
        "rule_id": request["rule_id"],
        "slot_number": 1,
        "attempt_number": 1,
        "profile_id": uid(304),
        "profile_digest": digest("synthetic execution profile"),
        "profile_head_revision": 1,
        "lease_id": checked.metadata["lease_id"],
        "lease_digest": checked.metadata["lease_digest"],
        "generation": 1,
        "fence": 1,
        "preflight_digest": checked.metadata["digest"],
        "send_token": uid(305),
        "send_until": (now + timedelta(seconds=90)).isoformat(),
        "request": deepcopy(request),
        "price_policy": policy_data(),
        "reserved_call_minor": 319488,
        "currency": "USD",
        "execution_method_digest": execution.method_digest(),
        "native_sql_method_digest": digest("synthetic catalog"),
        "execution_mode": "isolated_synthetic_mechanism",
        "recorded_by": "synthetic_execution_worker",
        "recorded_by_oid": 9001,
        "recorded_at": now.isoformat(),
        "mechanism_send_once_granted": True,
        **dict.fromkeys(execution.FALSE_FIELDS, False),
    }
    reserve = {
        "version": "material-execution-reservation/1",
        "job_id": d["job_id"],
        "job_digest": checked.metadata["job_digest"],
        "profile_id": d["profile_id"],
        "account_id": uid(306),
        "quote_digest": checked.metadata["quote_digest"],
        "request_set_digest": digest(checked.metadata["requests"]),
        "currency": "USD",
        "reserved_minor": 4_792_320,
        "per_call_reserved_minor": 319488,
        "execution_mode": "isolated_synthetic_mechanism",
        "execution_method_digest": execution.method_digest(),
        "recorded_at": now.isoformat(),
        "mechanism_fee_ledger_reserved": True,
        "account_price_confirmed": False,
        "formal_prediction_eligible": False,
        "invoice_reconciled": False,
    }
    return execution._observation(
        {
            "attempt": envelope(d),
            "reservation": envelope(reserve),
            "outcome": None,
            "job_balance": {
                "job_id": d["job_id"],
                "held_minor": reserve["reserved_minor"],
                "estimated_minor": 0,
                "released_minor": 0,
                "state": "in_flight",
            },
            "account_balance": {
                "account_id": reserve["account_id"],
                "held_minor": reserve["reserved_minor"],
                "estimated_minor": 0,
            },
            "new_send": True,
        }
    )


@pytest.fixture
def lane(owned, monkeypatch):
    checked = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    grant = sample(owned, checked)
    c = idle_connection()
    state = {"begins": [], "settled": [], "posts": []}

    def begin(connection, value, **kwargs):
        assert connection is c and value == checked
        state["begins"].append(kwargs)
        return grant

    def settle(connection, value, submitted, **kwargs):
        assert connection is c and value == grant
        state["settled"].append(submitted)
        return submitted

    monkeypatch.setattr(execution, "begin_attempt", begin)
    monkeypatch.setattr(execution, "settle", settle)
    d = grant.metadata["attempt"]["document"]
    args = {
        "rule_id": d["rule_id"],
        "slot_id": d["slot_id"],
        "profile_id": d["profile_id"],
        "expected_profile_digest": d["profile_digest"],
        "command_id": d["command_id"],
        "expected_preflight_digest": checked.metadata["digest"],
        "expected_method_digest": execution.method_digest(),
    }
    return SimpleNamespace(
        owned=owned, checked=checked, grant=grant, connection=c, state=state, args=args
    )


def run(lane, raw=None, *, status=200, handler=None):
    raw = response(judgment(lane.owned.bundle)) if raw is None else raw

    async def transport(request):
        assert lane.connection.info.transaction_status.name == "IDLE"
        assert lane.owned.connection.info.transaction_status.name == "IDLE"
        lane.state["posts"].append(request)
        if handler:
            return await handler(request)
        return httpx.Response(
            status, stream=Stream(raw), headers={"x-request-id": "synthetic-request"}
        )

    return asyncio.run(
        execution.execute_mechanism_attempt(
            lane.owned.connection,
            lane.connection,
            lane.owned.bundle,
            lane.checked,
            **lane.args,
            transport=httpx.MockTransport(transport),
        )
    )


def test_original_serializer_and_transport_are_called_once_and_valid_raw_is_kept(lane):
    result = run(lane)
    assert len(lane.state["begins"]) == len(lane.state["posts"]) == len(lane.state["settled"]) == 1
    assert result.metadata["valid_slot"] is True
    assert result.metadata["billing_state"] == "usage_reported"
    assert result.metadata["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }
    assert result.raw_response == response(judgment(lane.owned.bundle))
    expected = vision.prepare_request(
        lane.owned.bundle,
        lane.args["rule_id"],
        expected_input_digest=lane.owned.bundle.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    assert lane.state["posts"][0].content == expected.body
    assert str(lane.state["posts"][0].url) == vision.profile()["endpoint"]
    assert (
        not result.metadata["formal_prediction_eligible"]
        and not result.metadata["invoice_reconciled"]
    )
    assert "Synthetic" not in repr(result) and "send_token" not in repr(lane.grant)


@pytest.mark.parametrize("failure", ["wrong_citation", "invalid_json", "incomplete"])
def test_invalid_judgment_keeps_known_usage_and_raw_without_retry(lane, failure):
    data = judgment(lane.owned.bundle)
    raw = json.loads(response(data))
    if failure == "wrong_citation":
        data["evidence"][0]["quote"] = "invented quote"
        raw["choices"][0]["message"]["content"] = json.dumps(data)
    elif failure == "invalid_json":
        raw["choices"][0]["message"]["content"] = "{broken"
    else:
        raw["choices"][0]["finish_reason"] = "length"
    value = json.dumps(raw).encode()
    result = run(lane, value)
    assert not result.metadata["valid_slot"]
    assert result.metadata["billing_state"] == "usage_reported"
    assert result.metadata["usage"] == raw["usage"]
    assert result.raw_response == value and len(lane.state["posts"]) == 1


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_http_failure_records_unknown_and_does_not_retry(lane, status):
    result = run(lane, b"synthetic private failure", status=status)
    assert result.metadata["billing_state"] == "unknown" and result.metadata["usage"] is None
    assert result.raw_response == b"synthetic private failure" and result.metadata["raw_complete"]
    assert result.metadata["request_id"] == "synthetic-request"
    assert len(lane.state["posts"]) == 1 and len(lane.state["settled"]) == 1


def test_network_timeout_has_unknown_billing_and_exactly_one_attempt(lane):
    async def timeout(request):
        raise httpx.ReadTimeout("private transport detail", request=request)

    result = run(lane, handler=timeout)
    assert result.metadata["billing_state"] == "unknown"
    assert "private" not in repr(result) and result.raw_response == b""
    assert len(lane.state["posts"]) == 1


def test_cancellation_leaves_in_flight_reservation_and_never_resends(lane):
    async def cancelled(request):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        run(lane, handler=cancelled)
    assert len(lane.state["begins"]) == len(lane.state["posts"]) == 1
    assert lane.state["settled"] == []
    lane.grant.metadata["new_send"] = False
    assert run(lane) == lane.grant
    assert len(lane.state["posts"]) == 1


def test_lost_acknowledgment_or_new_command_cannot_replay_transport(lane):
    lane.grant.metadata["new_send"] = False
    lane.args["command_id"] = uid(399)
    assert run(lane) == lane.grant
    assert lane.state["posts"] == lane.state["settled"] == []


def test_expired_grant_before_transport_keeps_conservative_unknown_hold(lane):
    lane.grant.metadata["attempt"]["document"]["send_until"] = "2020-01-01T00:00:00Z"
    result = run(lane)
    assert lane.state["posts"] == []
    assert result.metadata["failure_code"] == "LEASE_EXPIRED_BEFORE_SEND"
    assert result.metadata["billing_state"] == "unknown"


def test_modified_original_pdf_fails_before_reservation_or_send(lane):
    originals = lane.owned.bundle.context.origin.originals
    originals[next(iter(originals))] += b"corruption"
    with pytest.raises(material.MaterialInputError, match="ORIGINAL_BYTES"):
        run(lane)
    assert lane.state["begins"] == lane.state["posts"] == []


def test_native_refusal_never_reaches_provider(lane, monkeypatch):
    def refuse(*args, **kwargs):
        execution.fail("CURRENT_STATE_UNAVAILABLE")

    monkeypatch.setattr(execution, "begin_attempt", refuse)
    with pytest.raises(execution.MaterialExecutionError, match="CURRENT_STATE_UNAVAILABLE"):
        run(lane)
    assert lane.state["posts"] == []


def test_settlement_failure_does_not_retry_or_swallow_uncertain_finances(lane, monkeypatch):
    def unavailable(*args, **kwargs):
        execution.fail("UNAVAILABLE")

    monkeypatch.setattr(execution, "settle", unavailable)
    with pytest.raises(execution.MaterialExecutionError, match="UNAVAILABLE"):
        run(lane)
    lane.grant.metadata["new_send"] = False
    assert run(lane) == lane.grant
    assert len(lane.state["posts"]) == 1


@pytest.mark.parametrize(
    "bad", [None, object(), SimpleNamespace(isolated_mechanism_transport=True)]
)
def test_only_explicit_http_mock_transport_can_enter_mechanism_lane(lane, bad):
    with pytest.raises(execution.MaterialExecutionError, match="ISOLATED_TRANSPORT_REQUIRED"):
        asyncio.run(
            execution.execute_mechanism_attempt(
                lane.owned.connection,
                lane.connection,
                lane.owned.bundle,
                lane.checked,
                **lane.args,
                transport=bad,
            )
        )
    assert lane.state["begins"] == []


def test_live_qualification_cannot_be_asserted_with_request_flags(lane):
    with pytest.raises(execution.MaterialExecutionError, match="LIVE_QUALIFICATION_UNAVAILABLE"):
        execution.execute_attempt(
            lane.checked,
            api_key="synthetic-key",
            account_price_confirmed=True,
            model_context_fit_proven=True,
            visual_readability_verified=True,
        )
    assert lane.state["begins"] == []


@pytest.mark.parametrize("change", ["boolean", "negative", "sum", "unsafe", "duplicate"])
def test_bad_usage_is_unknown_even_with_successful_http(lane, change):
    value = json.loads(response(judgment(lane.owned.bundle)))
    if change == "boolean":
        value["usage"]["prompt_tokens"] = True
    elif change == "negative":
        value["usage"]["completion_tokens"] = -1
    elif change == "sum":
        value["usage"]["total_tokens"] += 1
    elif change == "unsafe":
        value["usage"] = {"prompt_tokens": 2**54, "completion_tokens": 3, "total_tokens": 2**54 + 3}
    raw = json.dumps(value).encode()
    if change == "duplicate":
        raw = raw[:-1] + b',"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}'
    result = run(lane, raw)
    assert result.metadata["billing_state"] == "unknown"
    assert result.metadata["usage"] is None and len(lane.state["posts"]) == 1


@pytest.mark.parametrize("field", sorted(execution.FALSE_FIELDS))
def test_rehashed_native_attempt_cannot_grant_real_qualification(lane, field):
    value = deepcopy(lane.grant.metadata)
    value["attempt"]["document"][field] = True
    value["attempt"]["digest"] = digest(value["attempt"]["document"])
    with pytest.raises(execution.MaterialExecutionError, match="NATIVE_RESULT_INVALID"):
        execution._observation(value)
