"""Organizations, members and invitations (spec 5.2).

The LiteLLM bookkeeping (spend, budget, usage) lives in api/usage.py,
which imports ``_current_org`` and ``_org_budget`` from here."""

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.current_user import (
    CurrentUser,
    get_current_user,
    require_admin,
    require_platform_admin,
    user_memberships,
)
from auth.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER
from db.database import get_db
from logger import setup_logger
from models.invitation import Invitation
from models.membership import Membership
from models.organization import Organization
from models.user import User

router = APIRouter()
logger = setup_logger(__name__)


def _org_budget(org: Organization) -> float | None:
    return float(org.budget_usd) if org.budget_usd is not None else None


def _current_org(db: Session, user: CurrentUser) -> Organization:
    return (
        db.query(Organization).filter(Organization.id == user.org_id).first()
    )


SLUG_RULE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
ROLES = (ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER)


class OrganizationCreateRequest(BaseModel):
    slug: str = Field(pattern=SLUG_RULE.pattern)
    name: str = Field(min_length=1, max_length=120)


class MemberRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        return value


class InvitationCreateRequest(MemberRoleRequest):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value[1:-1]:
            raise ValueError("email must contain @")
        return value


def _membership_document(membership: Membership, org: Organization) -> dict:
    return {
        "id": str(org.id),
        "slug": org.slug,
        "name": org.name,
        "role": membership.role,
    }


def _member_document(membership: Membership, user: User) -> dict:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": membership.role,
        "created_at": membership.created_at,
        "last_seen_at": user.last_seen_at,
    }


def _invitation_document(invitation: Invitation) -> dict:
    return {
        "id": str(invitation.id),
        "email": invitation.email,
        "role": invitation.role,
        "invited_by": str(invitation.invited_by)
        if invitation.invited_by
        else None,
        "created_at": invitation.created_at,
        "accepted_at": invitation.accepted_at,
        "accepted_user_id": str(invitation.accepted_user_id)
        if invitation.accepted_user_id
        else None,
    }


def _admin_count(db: Session, org_id) -> int:
    return (
        db.query(func.count(Membership.id))
        .filter(Membership.org_id == org_id, Membership.role == ROLE_ADMIN)
        .scalar()
    )


def _find_member(db: Session, org_id, user_id: uuid.UUID) -> Membership:
    membership = (
        db.query(Membership)
        .filter(Membership.org_id == org_id, Membership.user_id == user_id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return membership


@router.get("/v1alpha1/organizations")
async def list_my_organizations(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    rows = user_memberships(db, user.id)
    return {
        "organizations": [_membership_document(m, o) for m, o in rows],
        "active": user.org_slug,
    }


@router.post("/v1alpha1/organizations", status_code=201)
async def create_organization(
    body: OrganizationCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_platform_admin),
):
    org = Organization(slug=body.slug, name=body.name)
    db.add(org)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"An organization with slug '{body.slug}' already exists",
        )
    membership = Membership(
        user_id=user.id,
        org_id=org.id,
        role=ROLE_ADMIN,
        created_at=datetime.now(),
    )
    db.add(membership)
    db.commit()
    return _membership_document(membership, org)


@router.get("/v1alpha1/organizations/current")
async def current_organization(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    org = _current_org(db, user)
    member_count = (
        db.query(func.count(Membership.id))
        .filter(Membership.org_id == org.id)
        .scalar()
    )
    return {
        "id": str(org.id),
        "slug": org.slug,
        "name": org.name,
        "role": user.role,
        "budget_usd": _org_budget(org),
        "member_count": member_count,
        "is_platform_admin": user.is_platform_admin,
    }


@router.get("/v1alpha1/organizations/current/members")
async def list_members(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    rows = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.org_id == user.org_id)
        .order_by(User.email, User.sub)
        .all()
    )
    return [_member_document(m, u) for m, u in rows]


@router.put("/v1alpha1/organizations/current/members/{user_id}")
async def change_member_role(
    user_id: uuid.UUID,
    body: MemberRoleRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    membership = _find_member(db, user.org_id, user_id)
    if (
        membership.role == ROLE_ADMIN
        and body.role != ROLE_ADMIN
        and _admin_count(db, user.org_id) <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="The organization needs at least one admin",
        )
    membership.role = body.role
    db.commit()
    member = db.get(User, user_id)
    return _member_document(membership, member)


@router.delete(
    "/v1alpha1/organizations/current/members/{user_id}", status_code=204
)
async def remove_member(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    if user_id == user.id:
        raise HTTPException(
            status_code=409, detail="You cannot remove yourself"
        )
    membership = _find_member(db, user.org_id, user_id)
    if membership.role == ROLE_ADMIN and _admin_count(db, user.org_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail="The organization needs at least one admin",
        )
    db.delete(membership)
    db.commit()
    return Response(status_code=204)


@router.get("/v1alpha1/organizations/current/invitations")
async def list_invitations(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    rows = (
        db.query(Invitation)
        .filter(Invitation.org_id == user.org_id)
        .order_by(Invitation.created_at.desc())
        .all()
    )
    return [_invitation_document(i) for i in rows]


@router.post("/v1alpha1/organizations/current/invitations", status_code=201)
async def create_invitation(
    body: InvitationCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    already = (
        db.query(Membership)
        .join(User, User.id == Membership.user_id)
        .filter(
            Membership.org_id == user.org_id,
            func.lower(User.email) == body.email,
        )
        .first()
    )
    if already is not None:
        raise HTTPException(
            status_code=409, detail=f"{body.email} is already a member"
        )
    invitation = (
        db.query(Invitation)
        .filter(
            Invitation.org_id == user.org_id,
            Invitation.email == body.email,
        )
        .first()
    )
    if invitation is None:
        invitation = Invitation(org_id=user.org_id, email=body.email)
        db.add(invitation)
    # Create or refresh: a re-sent invitation is pending again with the
    # new role.
    invitation.role = body.role
    invitation.invited_by = user.id
    invitation.created_at = datetime.now()
    invitation.accepted_at = None
    invitation.accepted_user_id = None
    db.commit()
    db.refresh(invitation)
    return _invitation_document(invitation)


@router.delete(
    "/v1alpha1/organizations/current/invitations/{invitation_id}",
    status_code=204,
)
async def withdraw_invitation(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    invitation = (
        db.query(Invitation)
        .filter(
            Invitation.id == invitation_id, Invitation.org_id == user.org_id
        )
        .first()
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at is not None:
        raise HTTPException(
            status_code=409, detail="The invitation was already accepted"
        )
    db.delete(invitation)
    db.commit()
    return Response(status_code=204)
