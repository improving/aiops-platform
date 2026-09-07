"""Personal API tokens (spec 5.4): ``aiops_<prefix>_<secret>``.

The database keeps ``prefix`` and ``sha256(secret)``; the full token is
shown once. This module has no FastAPI dependency so ``current_user``
can import it without a cycle; it raises ``TokenError`` and the caller
turns that into a 401.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models.api_token import ApiToken

TOKEN_PREFIX = "aiops_"
PREFIX_LENGTH = 8
SECRET_LENGTH = 32
SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPES = (SCOPE_READ, SCOPE_WRITE)
DEFAULT_EXPIRES_IN_DAYS = 90
MAX_EXPIRES_IN_DAYS = 365
# How long a last_used_at value is kept before it is written again.
LAST_USED_RESOLUTION = timedelta(minutes=1)

REVOKED = "The token was revoked"
EXPIRED = "The token has expired"
INVALID = "Invalid token"


class TokenError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _alnum(length: int) -> str:
    """``length`` characters of ``token_urlsafe`` output restricted to
    ``[A-Za-z0-9]``."""
    out = ""
    while len(out) < length:
        out += "".join(
            c for c in secrets.token_urlsafe(length * 2) if c.isalnum()
        )
    return out[:length]


def generate_token() -> tuple[str, str, str]:
    """``(prefix, secret, full token)``."""
    prefix = _alnum(PREFIX_LENGTH)
    secret = _alnum(SECRET_LENGTH)
    return prefix, secret, f"{TOKEN_PREFIX}{prefix}_{secret}"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def is_token(value: str | None) -> bool:
    return bool(value) and value.startswith(TOKEN_PREFIX)


def split_token(value: str) -> tuple[str, str] | None:
    if not is_token(value):
        return None
    parts = value[len(TOKEN_PREFIX) :].split("_")
    if len(parts) != 2:
        return None
    prefix, secret = parts
    if len(prefix) != PREFIX_LENGTH or len(secret) != SECRET_LENGTH:
        return None
    return prefix, secret


def authenticate_token(db: Session, value: str) -> ApiToken:
    """The token row for a full token, or ``TokenError``. Touches
    ``last_used_at`` at most once per minute; the caller commits."""
    parts = split_token(value)
    if parts is None:
        raise TokenError(INVALID)
    prefix, secret = parts
    token = db.query(ApiToken).filter(ApiToken.prefix == prefix).first()
    if token is None or not hmac.compare_digest(
        token.token_hash, hash_secret(secret)
    ):
        raise TokenError(INVALID)
    if token.revoked_at is not None:
        raise TokenError(REVOKED)
    now = datetime.now()
    if token.expires_at <= now:
        raise TokenError(EXPIRED)
    if (
        token.last_used_at is None
        or now - token.last_used_at > LAST_USED_RESOLUTION
    ):
        token.last_used_at = now
    return token
