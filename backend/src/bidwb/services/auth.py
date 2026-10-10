"""登录、会话与成员维护。

会话 ID 只存在于浏览器 cookie，库内保存其 SHA-256（``auth_sessions.id``）。成员停用后，其全部会话在下次请求时即失效
（查询时联结 ``members.active``），无需等待过期。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor
from bidwb.errors import Conflict, LoginFailed, TooManyRequests, Unprocessable
from bidwb.security import SessionSecrets, hash_password, needs_rehash, new_session_secrets, verify_password
from bidwb.services import audit
from bidwb.util import new_id, sha256_hex, utcnow

LOGIN_FAILED = "invalid_credentials"
MIN_PASSWORD_LENGTH = 12


class LoginRateLimiter:
    """进程内滑动窗口限流：同一登录名与同一来源地址各自计数。

    只是纵深防御；入口的 nginx 才是第一道限流。多进程部署时各进程独立计数，上限相应放大，可接受。
    """

    def __init__(self, limit: int, window_seconds: float = 60.0, clock: object | None = None) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._now = clock if callable(clock) else time.monotonic

    def check(self, *keys: str) -> None:
        now = self._now()
        with self._lock:
            for key in keys:
                hits = self._hits[key]
                while hits and now - hits[0] > self._window:
                    hits.popleft()
                if len(hits) >= self._limit:
                    raise TooManyRequests("login_rate_limited", "登录尝试过于频繁，请一分钟后再试")
            for key in keys:
                self._hits[key].append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)


def login_local(conn: Connection, *, username: str, password: str, ttl: timedelta, request_id: str) -> tuple[Actor, SessionSecrets]:
    """校验账号口令并创建会话。失败一律返回同一错误，不区分“无此账号”“口令错”“账号停用”。"""
    row = db.one(
        conn,
        """SELECT i.id AS identity_id, i.password_hash, m.id AS member_id, m.display_name, m.active
           FROM identities i JOIN members m ON m.id = i.member_id
           WHERE i.provider='local' AND i.subject = :subject""",
        {"subject": username},
    )
    password_ok = verify_password(row["password_hash"] if row else None, password)
    if row is None or not password_ok or not row["active"]:
        audit.record(
            conn,
            actor_id=row["member_id"] if row else None,
            project_id=None,
            action="auth.login_failed",
            object_kind="identity",
            object_id=row["identity_id"] if row else "unknown",
            request_id=request_id,
        )
        raise LoginFailed(LOGIN_FAILED, "账号或口令不正确")
    if needs_rehash(row["password_hash"]):
        db.run(conn, "UPDATE identities SET password_hash=:h WHERE id=:i", {"h": hash_password(password), "i": row["identity_id"]})
    return _open_session(conn, row, ttl, request_id)


def _open_session(conn: Connection, row: db.Row, ttl: timedelta, request_id: str) -> tuple[Actor, SessionSecrets]:
    secrets = new_session_secrets()
    now = utcnow()
    db.run(
        conn,
        "INSERT INTO auth_sessions(id,member_id,csrf_hash,created_at,expires_at) VALUES (:id,:m,:c,:now,:exp)",
        {"id": secrets.session_hash, "m": row["member_id"], "c": secrets.csrf_hash, "now": now, "exp": now + ttl},
    )
    db.run(conn, "UPDATE identities SET last_login_at=:now WHERE id=:i", {"now": now, "i": row["identity_id"]})
    audit.record(
        conn,
        actor_id=row["member_id"],
        project_id=None,
        action="auth.login",
        object_kind="session",
        object_id=secrets.session_hash[:12],
        request_id=request_id,
    )
    return _actor(row), secrets


def _actor(row: db.Row) -> Actor:
    return Actor(row["member_id"], row["display_name"])


def actor_for_session(conn: Connection, session_id: str) -> Actor | None:
    """按 cookie 里的会话 ID 找到有效会话的成员；无效、过期、撤销、成员停用均返回 ``None``。"""
    row = db.one(
        conn,
        """SELECT m.id AS member_id, m.display_name
           FROM auth_sessions s JOIN members m ON m.id = s.member_id
           WHERE s.id = :id AND s.revoked_at IS NULL AND s.expires_at > :now AND m.active""",
        {"id": sha256_hex(session_id), "now": utcnow()},
    )
    return _actor(row) if row else None


def revoke_session(conn: Connection, session_id: str) -> None:
    db.run(
        conn,
        "UPDATE auth_sessions SET revoked_at=:now WHERE id=:id AND revoked_at IS NULL",
        {"now": utcnow(), "id": sha256_hex(session_id)},
    )


def deactivate_member(conn: Connection, member_id: str, *, actor_id: str | None, request_id: str) -> None:
    """停用成员并立即撤销其全部会话。"""
    if db.run(conn, "UPDATE members SET active=false WHERE id=:m AND active", {"m": member_id}) == 0:
        raise Conflict("member_not_active", "成员不存在或已停用")
    db.run(conn, "UPDATE auth_sessions SET revoked_at=:now WHERE member_id=:m AND revoked_at IS NULL", {"now": utcnow(), "m": member_id})
    audit.record(
        conn,
        actor_id=actor_id,
        project_id=None,
        action="member.deactivate",
        object_kind="member",
        object_id=member_id,
        request_id=request_id,
    )


def create_local_member(conn: Connection, *, login: str, display_name: str, password: str, request_id: str = "cli") -> str:
    """创建成员及其本地身份；供管理命令使用。登录名不区分大小写，统一小写保存。"""
    login = login.strip().lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Unprocessable("weak_password", f"口令至少 {MIN_PASSWORD_LENGTH} 个字符")
    if db.one(conn, "SELECT 1 AS x FROM identities WHERE provider='local' AND subject=:s", {"s": login}):
        raise Conflict("login_taken", "登录名已存在")
    member_id = new_id("mem")
    db.run(
        conn,
        "INSERT INTO members(id,display_name,active,created_at) VALUES (:id,:n,true,:now)",
        {"id": member_id, "n": display_name, "now": utcnow()},
    )
    db.run(
        conn,
        "INSERT INTO identities(id,member_id,provider,subject,password_hash) VALUES (:id,:m,'local',:s,:h)",
        {"id": new_id("idn"), "m": member_id, "s": login, "h": hash_password(password)},
    )
    audit.record(
        conn,
        actor_id=None,
        project_id=None,
        action="member.create",
        object_kind="member",
        object_id=member_id,
        request_id=request_id,
        details={"login": login},
    )
    return member_id
