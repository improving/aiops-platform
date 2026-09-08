from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    PyJWKClientConnectionError,
    PyJWTError,
)
from sqlalchemy import func, nullsfirst
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.dev_users import (
    DEV_USER_HEADER,
    DEV_USERS,
    DevUser,
    dev_user,
    dev_user_header_honoured,
    ensure_dev_memberships,
    ensure_dev_organizations,
    warn_header_ignored_once,
)
from auth.errors import unauthorized
from auth.jwt import decode_token
from auth.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER, WRITER_ROLES
from auth.settings import MODE_DISABLED, auth_settings
from auth.tokens import SCOPE_READ, TokenError, authenticate_token, is_token
from db.database import get_db
from logger import setup_logger
from models.api_token import ApiToken
from models.invitation import Invitation
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User

logger = setup_logger(__name__)

AUTH_KIND_SESSION = "session"
AUTH_KIND_SERVICE = "service"
AUTH_KIND_TOKEN = "token"
AUTH_KIND_DEV = "dev"

ORG_HEADER = "X-Org"
NOT_A_MEMBER = "You are not a member of this organization"
NOT_PLATFORM_ADMIN = "This action needs the platform admin role"
MEMBERSHIP_GONE = "The token's organization membership is gone"

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
    # True when the realm roles contain "admin"; admin in every organization.
    is_platform_admin: bool = False
    # session, service, token or dev.
    auth_kind: str = AUTH_KIND_SESSION
    # The personal token's prefix when auth_kind is "token".
    token_prefix: str | None = None

    @property
    def is_default_org(self) -> bool:
        return self.org_slug == DEFAULT_ORG_SLUG

    @property
    def is_browser_session(self) -> bool:
        """A person signed in through the UI (or the dev user): the
        kinds that may open Langflow and be provisioned there. Service
        accounts and personal tokens are not people to Langflow."""
        return self.auth_kind in (AUTH_KIND_SESSION, AUTH_KIND_DEV)


@dataclass(frozen=True)
class Identity:
    """What a token says, before the database rows exist."""

    sub: str
    email: str | None
    name: str | None
    role: str
    is_service: bool
    is_platform_admin: bool = False
    auth_kind: str = AUTH_KIND_SESSION
    # Only a verified email may consume a pending invitation: otherwise a
    # self-service email change lets a user claim another address's invite.
    email_verified: bool = False


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
            auth_kind=AUTH_KIND_SERVICE,
        )
    sub = claims.get("sub")
    if not sub:
        raise unauthorized("The token has no subject")
    roles = set((claims.get("realm_access") or {}).get("roles") or ())
    return Identity(
        sub=sub,
        email=claims.get("email"),
        name=claims.get("name") or claims.get("preferred_username"),
        role=role_from_claims(claims),
        is_service=False,
        is_platform_admin=ROLE_ADMIN in roles,
        # Strict: only the literal boolean True counts as verified. A
        # misbehaving or malicious issuer sending the string "false" must
        # not be coerced truthy by a plain bool() cast.
        email_verified=claims.get("email_verified") is True,
    )


def identity_of(spec: DevUser) -> Identity:
    ident = spec.identity
    return Identity(
        sub=ident.sub,
        email=ident.email,
        name=ident.name,
        role=ident.role,
        is_service=False,
        is_platform_admin=ident.is_platform_admin,
        auth_kind=AUTH_KIND_DEV,
        email_verified=ident.email_verified,
    )


# Kept for any caller that still imports it.
DEV_IDENTITY = identity_of(DEV_USERS["dev"])


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
    db: Session,
    user: User,
    org: Organization,
    role: str,
    invited_by: UUID | None = None,
) -> Membership:
    """Create the membership when it is missing. The role is set once, at
    creation; an organization admin changes it afterwards through the API."""
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org.id)
        .first()
    )
    if membership is None:
        membership = Membership(
            user_id=user.id,
            org_id=org.id,
            role=role,
            created_at=datetime.now(),
            invited_by=invited_by,
        )
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
    return membership


def user_memberships(
    db: Session, user_id: UUID
) -> list[tuple[Membership, Organization]]:
    """The user's memberships, oldest first; pre-tenancy rows have no
    created_at and sort first on SQLite and Postgres alike."""
    return (
        db.query(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .filter(Membership.user_id == user_id)
        .order_by(nullsfirst(Membership.created_at), Organization.slug)
        .all()
    )


def accept_invitations(
    db: Session, user: User, email_verified: bool
) -> list[Membership]:
    """Turn every pending invitation for the user's email into a
    membership with the invitation's role. An invitation for an
    organization the user already belongs to is closed without touching
    the membership.

    Only a verified email may accept: otherwise a self-service email
    change at the identity provider would let a user consume another
    address's pending invitation. An unverified email leaves the
    invitation pending, with no error."""
    if not user.email or not email_verified:
        return []
    pending = (
        db.query(Invitation)
        .filter(
            func.lower(Invitation.email) == user.email.lower(),
            Invitation.accepted_at.is_(None),
        )
        .order_by(Invitation.created_at, Invitation.id)
        .all()
    )
    created = []
    now = datetime.now()
    for invitation in pending:
        org = db.get(Organization, invitation.org_id)
        if org is not None:
            created.append(
                _upsert_membership(
                    db, user, org, invitation.role, invitation.invited_by
                )
            )
        invitation.accepted_at = now
        invitation.accepted_user_id = user.id
    db.flush()
    return created


def resolve_user(
    db: Session,
    identity: Identity,
    org_slug: str | None = None,
    dev_spec: DevUser | None = None,
) -> CurrentUser:
    """Upsert the user, accept pending invitations, pick the active
    organization (spec 5.1)."""
    user = _upsert_user(db, identity)
    if dev_spec is not None:
        ensure_dev_memberships(db, user, dev_spec)
    accept_invitations(db, user, identity.email_verified)
    memberships = user_memberships(db, user.id)

    if identity.is_service:
        # Service accounts stay in the default organization.
        org = _default_organization(db)
        membership = _upsert_membership(db, user, org, identity.role)
    elif not memberships:
        # First login, no invitation: the default organization, with the
        # role the identity provider grants today.
        org = _default_organization(db)
        role = ROLE_ADMIN if identity.is_platform_admin else identity.role
        membership = _upsert_membership(db, user, org, role)
    elif org_slug:
        match = [(m, o) for m, o in memberships if o.slug == org_slug]
        if not match:
            db.commit()
            raise HTTPException(status_code=403, detail=NOT_A_MEMBER)
        membership, org = match[0]
    else:
        membership, org = memberships[0]
    db.commit()

    role = ROLE_ADMIN if identity.is_platform_admin else membership.role
    return CurrentUser(
        id=user.id,
        sub=user.sub,
        email=user.email,
        name=user.name,
        org_id=org.id,
        role=role,
        is_service=identity.is_service,
        org_slug=org.slug,
        is_platform_admin=identity.is_platform_admin,
        auth_kind=identity.auth_kind,
    )


def resolve_token_user(db: Session, token: ApiToken) -> CurrentUser:
    """A CurrentUser for the token's user in the token's organization.
    A ``read`` token is a viewer whatever the membership says."""
    user = db.get(User, token.user_id)
    org = db.get(Organization, token.org_id)
    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == token.user_id,
            Membership.org_id == token.org_id,
        )
        .first()
    )
    if user is None or org is None or membership is None:
        db.commit()
        raise unauthorized(MEMBERSHIP_GONE)
    now = datetime.now()
    if (
        user.last_seen_at is None
        or now - user.last_seen_at > LAST_SEEN_RESOLUTION
    ):
        user.last_seen_at = now
    db.commit()
    role = ROLE_VIEWER if token.scope == SCOPE_READ else membership.role
    return CurrentUser(
        id=user.id,
        sub=user.sub,
        email=user.email,
        name=user.name,
        org_id=org.id,
        role=role,
        is_service=False,
        org_slug=org.slug,
        is_platform_admin=False,
        auth_kind=AUTH_KIND_TOKEN,
        token_prefix=token.prefix,
    )


def as_member_of(
    db: Session, user: CurrentUser, org_id: UUID
) -> CurrentUser | None:
    """The same user, re-scoped to another organization they belong to;
    ``None`` without a membership there. The ext-authz route uses it,
    because the gateway forwards no ``X-Org``."""
    row = (
        db.query(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .filter(Membership.user_id == user.id, Membership.org_id == org_id)
        .first()
    )
    if row is None:
        return None
    membership, org = row
    return replace(
        user,
        org_id=org.id,
        org_slug=org.slug,
        role=ROLE_ADMIN if user.is_platform_admin else membership.role,
    )


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_org: str | None = Header(default=None, alias=ORG_HEADER),
    x_dev_user: str | None = Header(default=None, alias=DEV_USER_HEADER),
    db: Session = Depends(get_db),
) -> CurrentUser:
    user = _resolve_request(db, creds, x_org, x_dev_user)
    request.state.current_user = user
    return user


def _resolve_request(
    db: Session,
    creds: HTTPAuthorizationCredentials | None,
    x_org: str | None,
    x_dev_user: str | None,
) -> CurrentUser:
    org_slug = (x_org or "").strip().lower() or None
    if auth_settings().mode == MODE_DISABLED:
        spec = dev_user(x_dev_user if dev_user_header_honoured() else None)
        ensure_dev_organizations(db)
        return resolve_user(db, identity_of(spec), org_slug, dev_spec=spec)
    if x_dev_user is not None:
        warn_header_ignored_once()
    if creds is not None and is_token(creds.credentials):
        try:
            token = authenticate_token(db, creds.credentials)
        except TokenError as e:
            db.rollback()
            raise unauthorized(e.detail)
        return resolve_token_user(db, token)
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
    return resolve_user(db, identity_from_claims(claims), org_slug)


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


def require_platform_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail=NOT_PLATFORM_ADMIN)
    return user
