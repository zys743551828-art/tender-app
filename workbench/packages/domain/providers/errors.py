"""Controlled DeepSeek errors without application configuration imports."""

from packages.domain.errors import DomainError


class ProviderError(DomainError):
    """未知计费请求必须由调用账本/人工恢复处理，不能交普通重试器自动再付费。"""

    def __init__(self, code, message, *, billing_state="unknown", request_id=None, usage=None):
        details = {"provider": "deepseek", "billing_state": billing_state, "external_attempts": 1}
        if request_id:
            details["provider_request_id"] = request_id
        if usage is not None:
            details["usage"] = usage
        super().__init__(code, message, 503, details, retryable=False)
