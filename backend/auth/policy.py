"""Who may read or write a resource.

Every resource row carries ``org_id`` and ``owner_id``. Rows from before
the tenancy migration have ``org_id`` NULL and belong to the ``default``
organization; ``owner_id`` NULL means only an admin may change them.
"""

from fastapi import HTTPException
from sqlalchemy import and_, or_

from auth.current_user import CurrentUser
from auth.roles import ROLE_ADMIN, WRITER_ROLES


class Policy:
    @staticmethod
    def can_read(user: CurrentUser, resource) -> bool:
        """Same organization; viewers included."""
        if resource.org_id == user.org_id:
            return True
        return resource.org_id is None and user.is_default_org

    @staticmethod
    def is_owner_or_admin(user: CurrentUser, resource) -> bool:
        """Personal resources (notebooks) are visible to their owner and
        to the organization's admins only."""
        if not Policy.can_read(user, resource):
            return False
        if user.role == ROLE_ADMIN:
            return True
        return resource.owner_id is not None and resource.owner_id == user.id

    @staticmethod
    def can_write(user: CurrentUser, resource) -> bool:
        """The owner, or an admin of the organization."""
        if not Policy.can_read(user, resource):
            return False
        if user.role not in WRITER_ROLES:
            return False
        if user.role == ROLE_ADMIN:
            return True
        return resource.owner_id is not None and resource.owner_id == user.id


def org_scope(model, user: CurrentUser):
    """SQL clause selecting the rows of ``model`` the user may read."""
    if user.is_default_org:
        return or_(model.org_id == user.org_id, model.org_id.is_(None))
    return model.org_id == user.org_id


def owner_scope(model, user: CurrentUser):
    """SQL clause for personal resources: the owner's rows, or every row of
    the organization for an admin."""
    scope = org_scope(model, user)
    if user.role == ROLE_ADMIN:
        return scope
    return and_(scope, model.owner_id == user.id)


def not_owner(kind: str) -> HTTPException:
    return HTTPException(status_code=403, detail=f"You do not own this {kind}")


def authorize_read(user: CurrentUser, resource, kind: str) -> None:
    if not Policy.can_read(user, resource):
        raise not_owner(kind)


def authorize_owner(user: CurrentUser, resource, kind: str) -> None:
    if not Policy.is_owner_or_admin(user, resource):
        raise not_owner(kind)


def authorize_write(user: CurrentUser, resource, kind: str) -> None:
    if not Policy.can_write(user, resource):
        raise not_owner(kind)
