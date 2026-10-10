"""领域错误。

错误码是对外契约（见 contracts/openapi.json 的 Error），前端按 ``code`` 分支，``message`` 只给人看。
无权访问与不存在一律返回 404，避免泄露对象是否存在。
"""

from __future__ import annotations

from typing import Any, ClassVar


class DomainError(Exception):
    """所有可预期业务错误的基类。"""

    status: ClassVar[int] = 500
    retryable: ClassVar[bool] = False
    default_message: ClassVar[str] = "服务内部错误"
    # 少数错误要求“业务写入照常提交”（例如校验失败后的隔离记录必须保留），其余错误一律整体回滚。
    commit_on_error: ClassVar[bool] = False

    def __init__(self, code: str, message: str | None = None, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.message = message or self.default_message
        self.details = details


class Unauthorized(DomainError):
    status = 401
    default_message = "请先登录"


class Forbidden(DomainError):
    status = 403
    default_message = "没有执行该操作的权限"


class NotFound(DomainError):
    status = 404
    default_message = "对象不存在，或你无权访问"


class Conflict(DomainError):
    status = 409
    default_message = "当前状态不允许该操作"


class PreconditionFailed(DomainError):
    """If-Match 与当前版本不一致。"""

    status = 412
    default_message = "对象已被他人修改，请刷新后重试"


class PreconditionRequired(DomainError):
    status = 428
    default_message = "缺少必要的请求头"


class Unprocessable(DomainError):
    status = 422
    default_message = "请求内容不符合要求"


class TooManyRequests(DomainError):
    status = 429
    retryable = True
    default_message = "请求过于频繁，请稍后再试"


class Unavailable(DomainError):
    status = 503
    retryable = True
    default_message = "依赖服务暂不可用，请稍后重试"


class ContentMismatch(Unprocessable):
    """上传内容与声明不符：返回 422，但隔离记录与审计必须落库。"""

    commit_on_error = True


class LoginFailed(Unauthorized):
    """登录失败：返回 401，但“登录失败”审计记录必须落库。"""

    commit_on_error = True
