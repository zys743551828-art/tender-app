"""Explicit vendor/protocol registry. Only DeepSeek is implemented today."""

import os

from packages.domain.errors import DomainError
from packages.domain.providers.generation import DEEPSEEK_PROTOCOL, GenerationConfig

SUPPORTED_PORTS = frozenset({("deepseek", DEEPSEEK_PROTOCOL)})


class UnsupportedProvider(DomainError):
    def __init__(self):
        super().__init__(
            "MODEL_PROVIDER_UNSUPPORTED", "所选厂商或协议尚无已实现适配器", 503, retryable=False
        )


def require_supported(config: GenerationConfig):
    if (config.provider, config.protocol) not in SUPPORTED_PORTS:
        raise UnsupportedProvider()


def from_config(config: GenerationConfig, *, api_key, total_timeout=45.0, transport=None):
    require_supported(config)
    from packages.domain.providers.deepseek import DeepSeekClient

    return DeepSeekClient(
        api_key=api_key,
        model=config.model,
        base_url=config.base_url,
        total_timeout=total_timeout,
        transport=transport,
    )


def from_env():
    config = GenerationConfig.from_mapping(os.environ)
    require_supported(config)
    from packages.domain.providers.deepseek import DeepSeekClient

    # Preserve the existing facade and explicit offline-test injection seam.
    return DeepSeekClient.from_env()
