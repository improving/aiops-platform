"""What an audit event records and which requests get one (spec 5.3)."""

import re
from datetime import datetime

from sqlalchemy.orm import Session

from auth.current_user import AUTH_KIND_TOKEN, CurrentUser
from models.audit_event import AuditEvent

API_PREFIX = "/v1alpha1/"
# High volume and already attributed by LiteLLM; plus the ext-authz route,
# where Envoy replays the original method of every workload request.
EXCLUDED_PREFIXES = (
    "/v1alpha1/chat/",
    "/v1alpha1/embeddings",
    "/v1alpha1/rerank",
    "/v1alpha1/authz/",
)
# The MCP endpoint itself: one event per protocol message would drown the
# log (api/mcp.py logs each tool call instead). An exact path, because the
# writes under /v1alpha1/mcp/servers are recorded.
EXCLUDED_PATHS = ("/v1alpha1/mcp",)
READ_METHODS = ("GET", "HEAD", "OPTIONS")
# The operations stream's verbs, recorded as the action when they end the
# path.
VERBS = ("restart", "stop", "resume", "scale")
ACTIONS_BY_METHOD = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}
ANONYMOUS = "anonymous"

UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def should_record(method: str, path: str) -> bool:
    if method.upper() in READ_METHODS:
        return False
    if not path.startswith(API_PREFIX):
        return False
    if path.rstrip("/") in EXCLUDED_PATHS:
        return False
    return not path.startswith(EXCLUDED_PREFIXES)


def parse_path(path: str) -> tuple[str, str | None] | None:
    """``(resource_kind, resource_id)``: the segment after ``/v1alpha1/``
    and the first UUID-shaped segment after it."""
    if not path.startswith(API_PREFIX):
        return None
    segments = [s for s in path[len(API_PREFIX) :].split("/") if s]
    if not segments:
        return None
    kind = segments[0]
    resource_id = next(
        (s.lower() for s in segments[1:] if UUID_SEGMENT.match(s)), None
    )
    return kind, resource_id


def action_for(method: str, path: str) -> str:
    last = path.rstrip("/").rsplit("/", 1)[-1]
    if last in VERBS:
        return last
    return ACTIONS_BY_METHOD.get(method.upper(), method.lower())


def actor_label(user: CurrentUser | None) -> str:
    if user is None:
        return ANONYMOUS
    if user.auth_kind == AUTH_KIND_TOKEN and user.token_prefix:
        return f"token:{user.token_prefix}"
    if user.is_service:
        return user.sub
    return user.email or user.sub


def record(
    db: Session,
    *,
    user: CurrentUser | None,
    action: str,
    resource_kind: str,
    resource_id: str | None,
    outcome: int,
    request_id: str | None,
    detail: dict | None = None,
) -> AuditEvent:
    """Write one event with the caller's session; the caller commits."""
    event = AuditEvent(
        at=datetime.now(),
        org_id=user.org_id if user is not None else None,
        actor_id=user.id if user is not None else None,
        actor_label=actor_label(user),
        action=action,
        resource_kind=resource_kind,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id,
        detail=detail,
    )
    db.add(event)
    return event
