"""Assembly for the existing assistant budget authority; no new paid route.

The current SQL tariff/dispatch protocol binds a fixed DeepSeek wire profile.
Other transport endpoints require a reviewed authority migration before use here.
"""

from packages.domain.errors import DomainError
from packages.domain.providers import factory
from packages.domain.providers.generation import DEEPSEEK_PROTOCOL, GenerationConfig

LEGACY_ENDPOINTS = frozenset({"https://api.deepseek.com/v1"})


def require_budget_compatible(client):
    config = getattr(client, "config", None)
    if (
        not isinstance(config, GenerationConfig)
        or config.provider != "deepseek"
        or config.protocol != DEEPSEEK_PROTOCOL
        or config.base_url not in LEGACY_ENDPOINTS
        or config.model != client.model
    ):
        raise DomainError(
            "ASSISTANT_PROVIDER_PROFILE_UNSUPPORTED",
            "所选端点或协议尚未绑定助手费用授权，未发送；须先登记并审核费用协议",
            409,
            retryable=False,
        )
    return config


def configured():
    client = factory.from_env()
    require_budget_compatible(client)
    return client
