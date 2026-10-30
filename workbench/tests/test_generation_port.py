"""Offline contracts: routing is capability, never paid or scoring authority."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from packages.assistant.provider import require_budget_compatible
from packages.domain.errors import DomainError
from packages.domain.providers import factory
from packages.domain.providers.deepseek import DeepSeekClient, ProviderError
from packages.domain.providers.generation import Generation, GenerationConfig, execution_profile


def envelope(model):
    return {
        "id": "response-1",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_configured_model_and_endpoint_reuse_real_adapter_without_qualification():
    config = GenerationConfig(
        model="future-model-alias", base_url="https://configured.invalid/api/"
    )
    seen = []

    def handle(request):
        seen.append(request)
        assert str(request.url) == "https://configured.invalid/api/chat/completions"
        assert json.loads(request.content)["model"] == config.model
        return httpx.Response(200, json=envelope(config.model))

    client = factory.from_config(
        config, api_key="synthetic-offline", transport=httpx.MockTransport(handle)
    )
    generated = client.generate(messages=[{"role": "user", "content": "test"}])
    assert isinstance(client, DeepSeekClient) and isinstance(generated, Generation)
    assert len(seen) == 1 and generated.model == config.model
    assert generated.formal_scoring_eligible is False
    assert execution_profile(client, "core_review") == config.identity() | {
        "port": "generation/1",
        "purpose": "core_review",
        "formal_scoring_eligible": False,
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://configured.invalid/v1",
        "https://user@configured.invalid/v1",
        "https://user:secret@configured.invalid/v1",
        "https://configured.invalid/v1?key=secret",
        "https://configured.invalid/v1#fragment",
        "https://configured.invalid/v1?",
        "https://configured.invalid/v1#",
        "https:///v1",
        "https://configured.invalid:bad/v1",
        "https://configured.invalid:0/v1",
        "https://configured.invalid\\other/v1",
        "https://configured.invalid/../v1",
        "https://configured.invalid/white space",
    ],
)
def test_invalid_endpoint_fails_before_transport(endpoint):
    with pytest.raises(DomainError) as caught:
        GenerationConfig(base_url=endpoint)
    assert caught.value.code == "MODEL_CONFIG_INVALID"
    assert "secret" not in caught.value.message


@pytest.mark.parametrize("model", ["", "space alias", "a\nsecret", None, "a" * 201])
def test_model_identity_is_bounded_without_a_version_allowlist(model):
    with pytest.raises(DomainError):
        GenerationConfig(model=model)


@pytest.mark.parametrize(
    "config",
    [GenerationConfig(provider="unimplemented"), GenerationConfig(protocol="other-protocol/1")],
)
def test_unsupported_registry_selection_never_creates_an_adapter(config, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported selection cannot create a DeepSeek adapter")

    monkeypatch.setattr(DeepSeekClient, "__init__", forbidden)
    with pytest.raises(factory.UnsupportedProvider) as caught:
        factory.from_config(config, api_key="synthetic")
    assert caught.value.code == "MODEL_PROVIDER_UNSUPPORTED" and not caught.value.retryable


def test_explicit_process_config_overrides_legacy_and_does_not_contain_credentials():
    config = GenerationConfig.from_mapping(
        {
            "DEEPSEEK_MODEL": "legacy",
            "GENERATION_MODEL": "selected",
            "DEEPSEEK_BASE_URL": "https://legacy.invalid",
            "GENERATION_BASE_URL": "https://selected.invalid/v1",
            "DEEPSEEK_API_KEY": "never-retained",
        }
    )
    assert config.model == "selected" and config.base_url == "https://selected.invalid/v1"
    assert "never-retained" not in repr(config) + repr(config.identity())
    assert config.identity() != replace(config, protocol="other/1").identity()
    assert config.identity() != replace(config, base_url="https://other.invalid/v1").identity()


@pytest.mark.parametrize("fault", ["timeout", "network"])
def test_known_request_id_survives_stream_failure_without_resend(fault):
    seen = []

    class FailedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            error = httpx.ReadTimeout if fault == "timeout" else httpx.ReadError
            raise error("private transport information")

    def handle(request):
        seen.append(request)
        return httpx.Response(200, headers={"x-request-id": "known-request"}, stream=FailedStream())

    client = DeepSeekClient(api_key="synthetic", transport=httpx.MockTransport(handle))
    with pytest.raises(ProviderError) as caught:
        client.generate(messages=[{"role": "user", "content": "test"}])
    assert caught.value.details["provider_request_id"] == "known-request"
    assert caught.value.details["billing_state"] == "unknown"
    assert not caught.value.retryable and len(seen) == 1
    assert "private" not in caught.value.message


def test_async_cancellation_propagates_without_internal_retry():
    seen = []

    async def handle(request):
        seen.append(request)
        raise asyncio.CancelledError()

    client = DeepSeekClient(api_key="synthetic", transport=httpx.MockTransport(handle))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.generate_async(messages=[{"role": "user", "content": "test"}]))
    assert len(seen) == 1


def test_assistant_rejects_custom_endpoint_before_price_database_or_http(monkeypatch):
    from packages.assistant import budget, provider

    client = factory.from_config(
        GenerationConfig(base_url="https://configured.invalid/v1"), api_key="synthetic"
    )
    monkeypatch.setattr(factory, "from_env", lambda: client)
    for action in (provider.configured, lambda: budget.checked_price(None, client)):
        with pytest.raises(DomainError) as caught:
            action()
        assert caught.value.code == "ASSISTANT_PROVIDER_PROFILE_UNSUPPORTED"
        assert not caught.value.retryable


def test_assistant_default_is_compatible_but_new_model_does_not_get_a_price():
    from packages.assistant import budget

    client = factory.from_config(GenerationConfig(model="future-alias"), api_key="synthetic")
    require_budget_compatible(client)

    class NoPrice:
        def execute(self, statement, parameters):
            assert parameters == ("future-alias",)
            return self

        def fetchone(self):
            return None

    with pytest.raises(DomainError) as caught:
        budget.checked_price(NoPrice(), client)
    assert caught.value.code == "ASSISTANT_PRICE_UNAVAILABLE"
