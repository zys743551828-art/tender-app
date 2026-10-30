"""Vendor-neutral generation contract and trusted process configuration.

Configuration describes transport capability only. It grants no budget, model
qualification or permission to retry an unresolved paid request.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from packages.domain.errors import DomainError

DEEPSEEK_PROTOCOL = "deepseek-chat-completions/1"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
MODEL_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}"


@dataclass(frozen=True)
class Generation:
    content: str
    data: Any
    usage: dict[str, int]
    request_id: str
    response_id: str
    model: str
    finish_reason: str
    billing_state: str = "usage_reported"
    formal_scoring_eligible: bool = False


@dataclass(frozen=True)
class GenerationConfig:
    provider: str = "deepseek"
    protocol: str = DEEPSEEK_PROTOCOL
    model: str = "deepseek-flash"
    base_url: str = DEFAULT_BASE_URL

    def __post_init__(self):
        if (
            not isinstance(self.provider, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.provider)
            or not isinstance(self.protocol, str)
            or not re.fullmatch(r"[a-z][a-z0-9_./-]{0,99}", self.protocol)
            or not isinstance(self.model, str)
            or not re.fullmatch(MODEL_PATTERN, self.model)
        ):
            raise DomainError("MODEL_CONFIG_INVALID", "模型端口配置标识不合法", 503)
        try:
            if (
                not isinstance(self.base_url, str)
                or not 1 <= len(self.base_url) <= 2048
                or any(ord(char) <= 32 or ord(char) >= 127 for char in self.base_url)
                or "\\" in self.base_url
                or "?" in self.base_url
                or "#" in self.base_url
            ):
                raise ValueError("endpoint")
            location = urlsplit(self.base_url)
            if (
                location.scheme != "https"
                or not location.hostname
                or location.username is not None
                or location.password is not None
                or location.port == 0
                or any(part in {".", ".."} for part in location.path.split("/"))
            ):
                raise ValueError("endpoint")
        except ValueError:
            raise DomainError(
                "MODEL_CONFIG_INVALID", "模型端点须为显式合法HTTPS地址", 503
            ) from None
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]):
        """Only a composition root supplies this mapping; never an API request body."""
        return cls(
            provider=values.get("GENERATION_PROVIDER", "deepseek"),
            protocol=values.get("GENERATION_PROTOCOL", DEEPSEEK_PROTOCOL),
            model=values.get("GENERATION_MODEL", values.get("DEEPSEEK_MODEL", "deepseek-flash")),
            base_url=values.get(
                "GENERATION_BASE_URL", values.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
            ),
        )

    def identity(self):
        return {
            "provider": self.provider,
            "protocol": self.protocol,
            "model": self.model,
            "endpoint": self.base_url,
        }


class GenerationPort(Protocol):
    model: str
    config: GenerationConfig

    def generate(
        self, *, messages, max_tokens=256, json_schema=None, temperature=0
    ) -> Generation: ...

    async def generate_async(
        self, *, messages, max_tokens=256, json_schema=None, temperature=0
    ) -> Generation: ...


def execution_profile(client: GenerationPort, purpose: str):
    return client.config.identity() | {
        "port": "generation/1",
        "purpose": purpose,
        "formal_scoring_eligible": False,
    }
