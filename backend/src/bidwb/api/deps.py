"""请求级依赖：会话、CSRF、幂等键、If-Match。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from pydantic import BaseModel

from bidwb import db
from bidwb.access import Actor
from bidwb.errors import Forbidden, PreconditionRequired, Unauthorized, Unprocessable
from bidwb.runtime import Container
from bidwb.security import csrf_token_for
from bidwb.services import auth
from bidwb.services.idempotency import run_idempotent
from bidwb.util import constant_time_equals

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

Body = dict[str, Any]  # 写接口返回已序列化的响应体（幂等重放时直接取自库）


def container(request: Request) -> Container:
    c: Container = request.app.state.container
    return c


Ctr = Annotated[Container, Depends(container)]


def request_id(request: Request) -> str:
    rid: str = request.state.request_id
    return rid


@dataclass(frozen=True)
class Session:
    actor: Actor
    session_id: str
    request_id: str

    @property
    def csrf_token(self) -> str:
        return csrf_token_for(self.session_id)


def _session(request: Request, ctr: Container, *, check_csrf: bool) -> Session:
    session_id = request.cookies.get(ctr.settings.session_cookie_name)
    if not session_id:
        raise Unauthorized("auth_required")
    with ctr.engine.connect() as conn:
        actor = auth.actor_for_session(conn, session_id)
    if actor is None:
        raise Unauthorized("auth_required")
    if check_csrf and request.method not in SAFE_METHODS:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not constant_time_equals(supplied, csrf_token_for(session_id)):
            raise Forbidden("csrf_failed", "请求缺少有效的 CSRF 令牌，请刷新页面后重试")
    return Session(actor, session_id, request_id(request))


def current_session(request: Request, ctr: Ctr) -> Session:
    return _session(request, ctr, check_csrf=True)


CurrentSession = Annotated[Session, Depends(current_session)]


def idempotency_key(key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not key:
        raise PreconditionRequired("idempotency_key_required", "写请求必须携带 Idempotency-Key")
    return key


IdemKey = Annotated[str, Depends(idempotency_key)]


def if_match_revision(value: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    if value is None:
        raise PreconditionRequired("precondition_required", "更新必须携带 If-Match（对象当前版本号）")
    cleaned = value.strip().strip('"')
    if not cleaned.isdigit():
        raise Unprocessable("invalid_if_match", "If-Match 必须是对象版本号")
    return int(cleaned)


IfMatch = Annotated[int, Depends(if_match_revision)]


def mutate(
    ctr: Container,
    session: Session,
    key: str,
    operation: str,
    request_payload: Any,
    fn: Callable[[Any], BaseModel],
) -> dict[str, Any]:
    """在一个事务内执行写用例，并按（成员, 幂等键, 操作）保存/重放响应。"""
    payload = request_payload.model_dump(mode="json") if isinstance(request_payload, BaseModel) else request_payload
    with db.transaction(ctr.engine) as conn:
        _, body = run_idempotent(
            conn,
            member_id=session.actor.member_id,
            key=key,
            operation=operation,
            request=payload,
            handler=lambda: (200, fn(conn).model_dump(mode="json")),
        )
    return body
