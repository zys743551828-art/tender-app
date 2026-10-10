"""口令哈希与会话令牌。

* 口令使用 Argon2id（argon2-cffi 默认参数，已高于 OWASP 最低建议）。
* 会话 ID 只出现在 httpOnly cookie 里，库内仅存 SHA-256；库泄露不等于会话泄露。
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from bidwb.util import new_token, sha256_hex

_hasher = PasswordHasher()
# 用户不存在时也做一次等价哈希校验，避免通过响应时间枚举账号。
_DUMMY_HASH = _hasher.hash("bidwb-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def csrf_token_for(session_id: str) -> str:
    """CSRF 令牌由会话 ID 派生：只有持有会话 cookie 的一方能算出，``GET /me`` 可重复下发而无需在库内保存明文。

    跨站请求带得上 cookie，却读不到响应体里的令牌，也就无法在自定义请求头里回传——这是校验成立的前提
    （配合 SameSite=Lax 与严格的 CORS 策略）。
    """
    return sha256_hex(f"bidwb-csrf:{session_id}")


@dataclass(frozen=True)
class SessionSecrets:
    """新会话的明文凭据（只返回给调用方一次）及其库内哈希。"""

    session_id: str

    @property
    def session_hash(self) -> str:
        return sha256_hex(self.session_id)

    @property
    def csrf_token(self) -> str:
        return csrf_token_for(self.session_id)

    @property
    def csrf_hash(self) -> str:
        return sha256_hex(self.csrf_token)


def new_session_secrets() -> SessionSecrets:
    return SessionSecrets(session_id=new_token(32))
