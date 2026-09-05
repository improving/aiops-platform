from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    PyJWKClientConnectionError,
    PyJWTError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.jwt import decode_token
from auth.settings import MODE_DISABLED, auth_settings
from db.database import get_db
from logger import setup_logger
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User

logger = setup_logger(__name__)

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"
# Roles that may create and change resources.
WRITER_ROLES = (ROLE_ADMIN, ROLE_MEMBER)

# The identity every request gets in AUTH_MODE=disabled.
DEV_SUB = "dev"
DEV_EMAIL = "dev@example.test"
DEV_NAME = "Developer"

# How long a users.last_seen_at value is kept before it is written again.
LAST_SEEN_RESOLUTION = timedelta(minutes=1)

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: UUID
    sub: str
    email: str | None
    name: str | None
    org_id: UUID
    role: str
    is_service: bool
    org_slug: str = DEFAULT_ORG_SLUG

    @property
    def is_default_org(self) -> bool:
        return self.org_slug == DEFAULT_ORG_SLUG


@dataclass(frozen=True)
class Identity:
    """What a token says, before the database rows exist."""

    sub: str
    email: str | None
    name: str | None
    role: str
    is_service: bool


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def role_from_claims(claims: dict) -> str:
    roles = set((claims.get("realm_access") or {}).get("roles") or ())
    if ROLE_ADMIN in roles:
        return ROLE_ADMIN
    if ROLE_MEMBER in roles:
        return ROLE_MEMBER
    return ROLE_VIEWER


def identity_from_claims(claims: dict) -> Identity:
    """Map verified claims to an identity.

    A client-credentials token has no ``email`` and names its client in
    ``azp``; it becomes the service user ``svc:<azp>`` with the member role.
    """
    azp = claims.get("azp")
    if "email" not in claims and azp:
        return Identity(
            sub=f"svc:{azp}",
            email=None,
            name=azp,
            role=ROLE_MEMBER,
            is_service=True,
        )
    sub = claims.get("sub")
    if not sub:
        raise unauthorized("The token has no subject")
    return Identity(
        sub=sub,
        email=claims.get("email"),
        name=claims.get("name") or claims.get("preferred_username"),
        role=role_from_claims(claims),
        is_service=False,
    )


DEV_IDENTITY = Identity(
    sub=DEV_SUB,
    email=DEV_EMAIL,
    name=DEV_NAME,
    role=ROLE_ADMIN,
    is_service=False,
)


def _default_organization(db: Session) -> Organization:
    org = (
        db.query(Organization)
        .filter(Organization.slug == DEFAULT_ORG_SLUG)
        .first()
    )
    if org is None:
        raise HTTPException(
            status_code=500,
            detail="The default organization is missing; run the database migrations",
        )
    return org


def _upsert_user(db: Session, identity: Identity) -> User:
    user = db.query(User).filter(User.sub == identity.sub).first()
    if user is None:
        user = User(
            sub=identity.sub,
            email=identity.email,
            name=identity.name,
            last_seen_at=datetime.now(),
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Two first requests raced; the other one won.
            db.rollback()
            user = db.query(User).filter(User.sub == identity.sub).one()
        return user
    if user.email != identity.email:
        user.email = identity.email
    if user.name != identity.name:
        user.name = identity.name
    now = datetime.now()
    if (
        user.last_seen_at is None
        or now - user.last_seen_at > LAST_SEEN_RESOLUTION
    ):
        user.last_seen_at = now
    return user


def _upsert_membership(
    db: Session, user: User, org: Organization, role: str
) -> Membership:
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org.id)
        .first()
    )
    if membership is None:
        membership = Membership(user_id=user.id, org_id=org.id, role=role)
        db.add(membership)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            membership = (
                db.query(Membership)
                .filter(
                    Membership.user_id == user.id,
                    Membership.org_id == org.id,
                )
                .one()
            )
    if membership.role != role:
        # The identity provider owns the role.
        membership.role = role
    return membership


def resolve_user(db: Session, identity: Identity) -> CurrentUser:
    """Upsert the user and the default-organization membership."""
    org = _default_organization(db)
    user = _upsert_user(db, identity)
    membership = _upsert_membership(db, user, org, identity.role)
    db.commit()
    return CurrentUser(
        id=user.id,
        sub=user.sub,
        email=user.email,
        name=user.name,
        org_id=org.id,
        role=membership.role,
        is_service=identity.is_service,
        org_slug=org.slug,
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if auth_settings().mode == MODE_DISABLED:
        return resolve_user(db, DEV_IDENTITY)
    if creds is None:
        raise unauthorized(
            "Authentication required: send a bearer token in the Authorization header"
        )
    try:
        claims = decode_token(creds.credentials)
    except PyJWKClientConnectionError as e:
        logger.error("Cannot fetch the JWKS: %s", e)
        raise HTTPException(
            status_code=503,
            detail="The identity provider is not reachable; try again later",
        )
    except ExpiredSignatureError:
        raise unauthorized("The token has expired")
    except InvalidAudienceError:
        raise unauthorized("The token was not issued for this API")
    except InvalidIssuerError:
        raise unauthorized("The token was not issued by the expected issuer")
    except PyJWTError as e:
        raise unauthorized(f"Invalid token: {e}")
    return resolve_user(db, identity_from_claims(claims))


def require_role(*roles: str) -> Callable[..., CurrentUser]:
    """A dependency that resolves the user and checks the role."""
    allowed = " or ".join(roles)

    def dependency(
        user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action needs the {allowed} role",
            )
        return user

    return dependency


require_writer = require_role(*WRITER_ROLES)
require_admin = require_role(ROLE_ADMIN)
