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
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from auth.current_user import CurrentUser, get_current_user
from auth.policy import Policy, not_owner
from db.database import get_db
from logger import setup_logger
from models.inference_instance import DBInferenceInstance
from models.notebook import Notebook
from models.vectordb_instance import DBVectorDBInstance
from utils.hostnames import parse_hostname

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
    # The last eight hex characters of the id; the cast gives hex on
    # SQLite and the dashed text on Postgres, and both end with them.
    row = (
        db.query(model).filter(cast(model.id, String).like(f"%{id8}")).first()
    )
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
