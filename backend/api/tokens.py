"""``/v1alpha1/tokens``: personal API tokens of the caller in the active
organization (spec 5.4). A token cannot manage tokens."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.current_user import (
    AUTH_KIND_SERVICE,
    AUTH_KIND_TOKEN,
    CurrentUser,
    get_current_user,
)
from auth.roles import ROLE_ADMIN
from auth.tokens import (
    DEFAULT_EXPIRES_IN_DAYS,
    MAX_EXPIRES_IN_DAYS,
    SCOPES,
    generate_token,
    hash_secret,
)
from db.database import get_db
from models.api_token import ApiToken

router = APIRouter()

TOKENS_NEED_A_SESSION = "A token cannot manage tokens"
SERVICE_NEEDS_A_SESSION = "Only a signed-in user can manage tokens"


class TokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str
    expires_in_days: int = Field(
        default=DEFAULT_EXPIRES_IN_DAYS, ge=1, le=MAX_EXPIRES_IN_DAYS
    )

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        if value not in SCOPES:
            raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
        return value


class TokenSchema(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class TokenCreatedSchema(TokenSchema):
    # The full token, shown once.
    token: str


def require_session_identity(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.auth_kind == AUTH_KIND_TOKEN:
        raise HTTPException(status_code=403, detail=TOKENS_NEED_A_SESSION)
    if user.auth_kind == AUTH_KIND_SERVICE:
        raise HTTPException(status_code=403, detail=SERVICE_NEEDS_A_SESSION)
    return user


@router.get("/v1alpha1/tokens", response_model=list[TokenSchema])
def list_tokens(
    all: bool = Query(
        default=False, description="Every token of the organization; admins"
    ),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_session_identity),
):
    query = db.query(ApiToken).filter(ApiToken.org_id == user.org_id)
    if all:
        if user.role != ROLE_ADMIN:
            raise HTTPException(
                status_code=403, detail="This action needs the admin role"
            )
    else:
        query = query.filter(ApiToken.user_id == user.id)
    return query.order_by(ApiToken.created_at.desc()).all()


def _new_token_row(user: CurrentUser, body: TokenCreateRequest):
    """A fresh, unsaved token row and the full token it hashes."""
    prefix, secret, full = generate_token()
    now = datetime.now()
    row = ApiToken(
        user_id=user.id,
        org_id=user.org_id,
        name=body.name,
        prefix=prefix,
        token_hash=hash_secret(secret),
        scope=body.scope,
        created_at=now,
        expires_at=now + timedelta(days=body.expires_in_days),
    )
    return row, full


@router.post(
    "/v1alpha1/tokens", response_model=TokenCreatedSchema, status_code=201
)
def create_token(
    body: TokenCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_session_identity),
):
    # ``prefix`` is drawn from a small alphabet at a short, fixed length,
    # so a collision with another organization's token is rare but not
    # impossible (spec: unique across every organization); one retry with
    # a freshly generated prefix, then give up.
    row, full = _new_token_row(user, body)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row, full = _new_token_row(user, body)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Could not mint a unique token; try again",
            )
    db.refresh(row)
    return TokenCreatedSchema(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scope=row.scope,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        token=full,
    )


@router.delete("/v1alpha1/tokens/{token_id}", status_code=204)
def revoke_token(
    token_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_session_identity),
):
    query = db.query(ApiToken).filter(
        ApiToken.id == token_id, ApiToken.org_id == user.org_id
    )
    if user.role != ROLE_ADMIN:
        query = query.filter(ApiToken.user_id == user.id)
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now()
        db.commit()
    return Response(status_code=204)
