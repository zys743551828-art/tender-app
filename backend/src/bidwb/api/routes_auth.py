"""登录、登出、当前用户。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response

from bidwb import db
from bidwb.api.deps import Ctr, CurrentSession, request_id
from bidwb.schemas import LoginRequest, Me
from bidwb.services import auth

router = APIRouter(tags=["auth"])


def _me(actor_id: str, name: str, csrf: str) -> Me:
    return Me(member_id=actor_id, display_name=name, csrf_token=csrf)


@router.post("/auth/login", response_model=Me, operation_id="login")
def login(body: LoginRequest, request: Request, response: Response, ctr: Ctr) -> Me:
    """账号口令登录。成功后下发 httpOnly 会话 cookie，并返回 CSRF 令牌。"""
    username = body.username.strip().lower()
    client = request.client.host if request.client else "unknown"
    ctr.login_limiter.check(f"user:{username}", f"ip:{client}")
    ttl = timedelta(hours=ctr.settings.session_ttl_hours)
    with db.transaction(ctr.engine) as conn:
        actor, secrets = auth.login_local(conn, username=username, password=body.password, ttl=ttl, request_id=request_id(request))
    response.set_cookie(
        ctr.settings.session_cookie_name,
        secrets.session_id,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=ctr.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return _me(actor.member_id, actor.display_name, secrets.csrf_token)


@router.get("/me", response_model=Me, operation_id="getMe")
def me(session: CurrentSession) -> Me:
    return _me(session.actor.member_id, session.actor.display_name, session.csrf_token)


@router.post("/auth/logout", status_code=204, operation_id="logout")
def logout(session: CurrentSession, ctr: Ctr) -> Response:
    with db.transaction(ctr.engine) as conn:
        auth.revoke_session(conn, session.session_id)
    out = Response(status_code=204)
    out.delete_cookie(ctr.settings.session_cookie_name, path="/")
    return out
