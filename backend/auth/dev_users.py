"""Test-only impersonation (spec section 5.6).

With ``AUTH_MODE=disabled`` and ``TEST_MODE=true`` the ``X-Dev-User``
header names one of five fixed identities. Organization ``other`` and
the memberships below are seeded lazily, on the first dev-identity
resolution, so ``core.create_app`` stays untouched.
"""

import os
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.errors import unauthorized
from auth.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER
from auth.settings import MODE_DISABLED, auth_settings
from logger import setup_logger
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User

logger = setup_logger(__name__)

DEV_USER_HEADER = "X-Dev-User"
OTHER_ORG_SLUG = "other"
OTHER_ORG_NAME = "Other"

# The identity every request gets in AUTH_MODE=disabled without a header.
DEV_SUB = "dev"
DEV_EMAIL = "dev@example.test"
DEV_NAME = "Developer"


@dataclass(frozen=True)
class DevIdentity:
    sub: str
    email: str
    name: str
    role: str
    is_platform_admin: bool
    # Dev identities always carry a verified email.
    email_verified: bool = True


@dataclass(frozen=True)
class DevUser:
    identity: DevIdentity
    # (organization slug, membership role), created on first resolution.
    memberships: tuple[tuple[str, str], ...]


def _person(name: str, role: str, platform_admin: bool = False) -> DevIdentity:
    return DevIdentity(
        sub=f"dev:{name}",
        email=f"{name}@example.test",
        name=name.capitalize(),
        role=role,
        is_platform_admin=platform_admin,
    )


DEV_USERS: dict[str, DevUser] = {
    "dev": DevUser(
        DevIdentity(DEV_SUB, DEV_EMAIL, DEV_NAME, ROLE_ADMIN, True),
        ((DEFAULT_ORG_SLUG, ROLE_ADMIN), (OTHER_ORG_SLUG, ROLE_ADMIN)),
    ),
    "alice": DevUser(
        _person("alice", ROLE_MEMBER), ((DEFAULT_ORG_SLUG, ROLE_MEMBER),)
    ),
    "bob": DevUser(
        _person("bob", ROLE_MEMBER), ((DEFAULT_ORG_SLUG, ROLE_MEMBER),)
    ),
    "viewer": DevUser(
        _person("viewer", ROLE_VIEWER), ((DEFAULT_ORG_SLUG, ROLE_VIEWER),)
    ),
    # An organization admin who is no platform admin: what an imported
    # catalog draft must stay invisible to.
    "orgadmin": DevUser(
        _person("orgadmin", ROLE_ADMIN), ((DEFAULT_ORG_SLUG, ROLE_ADMIN),)
    ),
    "outsider": DevUser(
        _person("outsider", ROLE_MEMBER), ((OTHER_ORG_SLUG, ROLE_MEMBER),)
    ),
}

_warned = False


def dev_user_header_honoured() -> bool:
    return (
        auth_settings().mode == MODE_DISABLED
        and os.environ.get("TEST_MODE", "").lower() == "true"
    )


def warn_header_ignored_once() -> None:
    """Log once that ``X-Dev-User`` was sent but is not honoured."""
    global _warned
    if _warned:
        return
    _warned = True
    logger.warning(
        "%s is ignored: it needs AUTH_MODE=disabled and TEST_MODE=true",
        DEV_USER_HEADER,
    )


def dev_user(name: str | None) -> DevUser:
    """The dev user for the header value; ``None`` is ``dev``."""
    key = (name or "dev").strip().lower()
    if key not in DEV_USERS:
        raise unauthorized(f"Unknown dev user '{name}'")
    return DEV_USERS[key]


def ensure_dev_organizations(db: Session) -> None:
    """Create organization ``other`` when it is missing (idempotent)."""
    exists = (
        db.query(Organization)
        .filter(Organization.slug == OTHER_ORG_SLUG)
        .first()
    )
    if exists is None:
        db.add(Organization(slug=OTHER_ORG_SLUG, name=OTHER_ORG_NAME))
        try:
            db.commit()
        except IntegrityError:
            # Two concurrent first requests raced; the other one won.
            db.rollback()


def ensure_dev_memberships(db: Session, user: User, spec: DevUser) -> None:
    """Create the fixed memberships of a dev user when missing."""
    for slug, role in spec.memberships:
        org = db.query(Organization).filter(Organization.slug == slug).one()
        membership = (
            db.query(Membership)
            .filter(Membership.user_id == user.id, Membership.org_id == org.id)
            .first()
        )
        if membership is None:
            db.add(
                Membership(
                    user_id=user.id,
                    org_id=org.id,
                    role=role,
                    created_at=datetime.now(),
                )
            )
            try:
                db.flush()
            except IntegrityError:
                # Two concurrent first requests raced; the other one won.
                db.rollback()
                db.query(Membership).filter(
                    Membership.user_id == user.id, Membership.org_id == org.id
                ).one()
    db.flush()
