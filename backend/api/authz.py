"""The ext-authz endpoint the gateway calls before it forwards a request.

Envoy sends the original ``Host`` and ``Authorization`` headers of every
request to a workload host (``nb-<id8>``, ``vdb-<id8>``, ``vdb-<id8>-api``,
``inf-<id8>``). The answer is 200 with identity headers the gateway copies
to the upstream, 403 when the user may not use the instance, 404 when the
host is not an instance, and 401 without a valid token (the dependency).
See docs/superpowers/plans/2026-09-04-authentication.md, Task 9.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth.current_user import (
    AUTH_KIND_TOKEN,
    CurrentUser,
    as_member_of,
    get_current_user,
)
from auth.policy import Policy, not_owner
from db.database import get_db
from logger import setup_logger
from models.inference_instance import DBInferenceInstance
from models.notebook import Notebook
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.vectordb_instance import DBVectorDBInstance
from utils.hostnames import parse_hostname
from utils.ids import find_by_id8

router = APIRouter()
logger = setup_logger(__name__)

# Per host kind: the table, the name used in error details, and the
# check. Notebooks are personal (owner or org admin); vector databases
# and inference endpoints are shared inside the organization.
_RULES: dict[str, tuple[type, str, Callable[[CurrentUser, object], bool]]] = {
    "nb": (Notebook, "notebook", Policy.can_write),
    "vdb": (DBVectorDBInstance, "vector database instance", Policy.can_read),
    "inf": (DBInferenceInstance, "inference instance", Policy.can_read),
}

EXPECTED_HOSTS = "nb-<id>, vdb-<id>, vdb-<id>-api or inf-<id>"


def requested_host(host: str | None, forwarded_host: str | None) -> str:
    """The host the user asked for; ``X-Forwarded-Host`` wins when set."""
    if forwarded_host:
        return forwarded_host.split(",", 1)[0].strip()
    return (host or "").strip()


# Envoy appends the original method and path to extAuth.http.path, so this
# must answer every method on every sub-path (POST /api/sessions, WebSocket
# upgrades on /api/kernels/<id>/channels, ...).
@router.api_route(
    "/v1alpha1/authz/route{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
def authorize_route(
    path: str = "",
    host: str | None = Header(default=None),
    x_forwarded_host: str | None = Header(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    requested = requested_host(host, x_forwarded_host)
    parsed = parse_hostname(requested)
    if parsed is None:
        logger.info(
            "authz host=%r forwarded_host=%r sub=%s decision=unknown-host",
            host,
            x_forwarded_host,
            user.sub,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Unknown host {requested!r}: expected {EXPECTED_HOSTS}",
        )
    kind, id8, _suffix = parsed
    model, label, allowed = _RULES[kind]
    row = find_by_id8(db, model, id8)
    if row is None:
        logger.info(
            "authz host=%r forwarded_host=%r sub=%s decision=no-instance",
            host,
            x_forwarded_host,
            user.sub,
        )
        raise HTTPException(
            status_code=404, detail=f"No {label} for host {requested!r}"
        )
    # The gateway forwards "authorization" and "cookie" only (utils/gateway.py
    # headersToExtAuth), and the UI's aiops_org cookie lives on the UI host,
    # so X-Org never arrives: the caller shows up in their first
    # organization. Evaluate the policy as a member of the resource's
    # organization instead. A personal token is bound to one organization
    # and is not re-scoped.
    if user.auth_kind != AUTH_KIND_TOKEN:
        if row.org_id is not None and row.org_id != user.org_id:
            user = as_member_of(db, user, row.org_id) or user
        elif row.org_id is None and not user.is_default_org:
            # A row from before the tenancy migration belongs to the
            # default organization (auth/policy.py Policy.can_read);
            # re-scope a caller who is a member there but currently
            # active in another organization.
            default_org = (
                db.query(Organization)
                .filter(Organization.slug == DEFAULT_ORG_SLUG)
                .first()
            )
            if default_org is not None:
                user = as_member_of(db, user, default_org.id) or user
    decision = "allow" if allowed(user, row) else "deny"
    logger.info(
        "authz host=%r forwarded_host=%r sub=%s %s=%s decision=%s",
        host,
        x_forwarded_host,
        user.sub,
        label.replace(" ", "_"),
        row.id,
        decision,
    )
    if decision == "deny":
        raise not_owner(label)
    return JSONResponse(
        content={},
        headers={
            "X-Auth-User-Email": user.email or "",
            "X-Auth-User-Sub": user.sub,
            "X-Auth-Org": user.org_slug,
        },
    )
