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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.api_token import ApiToken

TOKEN_PREFIX = "aiops_"
PREFIX_LENGTH = 8
SECRET_LENGTH = 32
SCOPE_READ = "read"
SCOPE_WRITE = "write"
# Valid on the MCP endpoint only (auth/current_user.py), with the
# member's own role there: what an IDE or a Langflow flow holds, so that
# a leaked tool token cannot create or delete platform resources.
SCOPE_MCP = "mcp"
MCP_PATH = "/v1alpha1/mcp"
SCOPES = (SCOPE_READ, SCOPE_WRITE, SCOPE_MCP)
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


class TokenMintError(Exception):
    """Two generated prefixes in a row were taken."""


def mint_token(
    db,
    *,
    user_id,
    org_id,
    name: str,
    scope: str,
    expires_in_days: int,
) -> tuple[ApiToken, str]:
    """A committed token row and the full token, shown this once.
    ``prefix`` is short and drawn from a small alphabet, so a collision
    with another token is rare but possible: one retry, then give up."""
    for _ in range(2):
        prefix, secret, full = generate_token()
        now = datetime.now()
        row = ApiToken(
            user_id=user_id,
            org_id=org_id,
            name=name,
            prefix=prefix,
            token_hash=hash_secret(secret),
            scope=scope,
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(row)
        return row, full
    raise TokenMintError("Could not mint a unique token; try again")


# A token the platform keeps for the user in another system (Langflow's
# MCP variable) is renewed when it has less than this left.
MANAGED_RENEW_BEFORE = timedelta(days=30)


def ensure_managed_token(
    db, *, user_id, org_id, name: str, scope: str, holder_has_it: bool
) -> str | None:
    """The token named ``name`` that the platform manages for this user
    and organization: ``None`` when the holder still has a live one,
    else a new token (the old rows deleted, not revoked: this runs on
    every page load of the holder, and a list of revoked rows would
    grow without end). A stored token cannot be read back, which is why
    the caller says whether the holder has it."""
    now = datetime.now()
    rows = (
        db.query(ApiToken)
        .filter(
            ApiToken.user_id == user_id,
            ApiToken.org_id == org_id,
            ApiToken.name == name,
            ApiToken.scope == scope,
        )
        .all()
    )
    live = [
        r
        for r in rows
        if r.revoked_at is None and r.expires_at - now > MANAGED_RENEW_BEFORE
    ]
    # The holder keeps ONE token for the user, whatever the organization
    # (one Langflow variable). What it holds is the newest one minted
    # under this name: when that was for another organization, the
    # holder does not have this organization's token, whatever it says.
    newest = (
        db.query(ApiToken)
        .filter(
            ApiToken.user_id == user_id,
            ApiToken.name == name,
            ApiToken.scope == scope,
        )
        .order_by(ApiToken.created_at.desc())
        .first()
    )
    held_here = newest is not None and newest.org_id == org_id
    if holder_has_it and held_here and live:
        return None
    for row in rows:
        db.delete(row)
    db.flush()
    _, full = mint_token(
        db,
        user_id=user_id,
        org_id=org_id,
        name=name,
        scope=scope,
        expires_in_days=MAX_EXPIRES_IN_DAYS,
    )
    return full
