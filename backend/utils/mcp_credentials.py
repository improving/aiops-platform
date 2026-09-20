"""The credentials of MCP servers: where they are stored and how one
becomes request headers.

``resolve`` is the one place that answers "which headers does this
caller's request to this server carry". With no credential, or one the
organization shares (LiteLLM holds a copy of it), the relay adds
nothing. Where each member brings their own (``per_user``), the value
is read from the member's Secret and goes to LiteLLM as
``x-mcp-<alias>-<header>``, which the proxy forwards to that server for
that call only (measured: two callers, two credentials, no mixing).
OAuth is a later mode of the same call. The Secret is the source of
truth in every mode.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from auth.current_user import CurrentUser
from models.mcp_server import McpCredential, McpServer
from utils.gateway import id8
from utils.kubernetes_utils import get_default_namespace
from utils.secret_store import get_secret_store

SECRET_KEY = "credential"
MODE_NONE = "none"
MODE_SHARED = "shared"
MODE_PER_USER = "per_user"
CREDENTIAL_MODES = (MODE_NONE, MODE_SHARED, MODE_PER_USER)
# A member's value is read on every MCP request; keep it this long.
VALUE_CACHE_SECONDS = 60.0
_value_cache: dict[str, tuple[float, str]] = {}
AUTH_BEARER = "bearer"
AUTH_HEADER = "header"
AUTH_TYPES = (AUTH_BEARER, AUTH_HEADER)

# What GET /mcp/servers says about the caller's own credential.
NOT_NEEDED = "not_needed"
SET = "set"
MISSING = "missing"


@dataclass(frozen=True)
class Resolved:
    """``state`` is one of NOT_NEEDED, SET, MISSING; ``headers`` is
    what the relay must add for this caller (nothing while LiteLLM
    holds the shared credential)."""

    state: str
    headers: dict[str, str]


def shared_secret_name(server_id: uuid.UUID) -> str:
    return f"mcp-{id8(server_id)}-credentials"


def user_secret_name(server_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"mcp-{id8(server_id)}-usr-{id8(user_id)}-credentials"


def credential_headers(
    auth_type: str, auth_header: str | None, value: str
) -> dict[str, str]:
    """The upstream request headers one credential value becomes."""
    if auth_type == AUTH_HEADER:
        return {auth_header or "Authorization": value}
    return {"Authorization": f"Bearer {value}"}


def shared_credential(server: McpServer) -> McpCredential | None:
    return next((c for c in server.credentials if c.user_id is None), None)


def store_shared(
    db: Session,
    server: McpServer,
    auth_type: str,
    auth_header: str | None,
    value: str,
) -> McpCredential:
    """Write the Secret first, then the row that points at it."""
    name = shared_secret_name(server.id)
    get_secret_store().write(
        get_default_namespace(), name, {SECRET_KEY: value}
    )
    row = shared_credential(server)
    if row is None:
        row = McpCredential(server_id=server.id, user_id=None)
        server.credentials.append(row)
    row.secret_name = name
    row.auth_type = auth_type
    row.auth_header = auth_header if auth_type == AUTH_HEADER else None
    # Said explicitly: a new value in the same header shape changes no
    # column, so ``onupdate`` would leave the "set" date of the old one.
    row.updated_at = datetime.now()
    db.flush()
    return row


def read_value(credential: McpCredential) -> str | None:
    return get_secret_store().read(
        get_default_namespace(), credential.secret_name, SECRET_KEY
    )


def delete_all(server: McpServer) -> None:
    """Every Secret of the server; the rows go with the server."""
    store = get_secret_store()
    namespace = get_default_namespace()
    for credential in list(server.credentials):
        store.delete(namespace, credential.secret_name)


def delete_shared(db: Session, server: McpServer) -> None:
    row = shared_credential(server)
    if row is None:
        return
    get_secret_store().delete(get_default_namespace(), row.secret_name)
    server.credentials.remove(row)
    db.flush()


def user_credential(
    server: McpServer, user_id: uuid.UUID
) -> McpCredential | None:
    return next((c for c in server.credentials if c.user_id == user_id), None)


def store_for_user(
    db: Session, server: McpServer, user_id: uuid.UUID, value: str
) -> McpCredential:
    """A member's own value, in the header shape the server asks for."""
    name = user_secret_name(server.id, user_id)
    get_secret_store().write(
        get_default_namespace(), name, {SECRET_KEY: value}
    )
    _value_cache.pop(name, None)
    row = user_credential(server, user_id)
    if row is None:
        row = McpCredential(server_id=server.id, user_id=user_id)
        server.credentials.append(row)
    row.secret_name = name
    row.auth_type = server.user_auth_type or AUTH_BEARER
    row.auth_header = server.user_auth_header
    row.updated_at = datetime.now()
    db.flush()
    return row


def delete_for_user_on_server(
    db: Session, server: McpServer, user_id: uuid.UUID
) -> bool:
    row = user_credential(server, user_id)
    if row is None:
        return False
    get_secret_store().delete(get_default_namespace(), row.secret_name)
    _value_cache.pop(row.secret_name, None)
    server.credentials.remove(row)
    db.flush()
    return True


def delete_for_user(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Every credential a member stored in one organization: what
    ``remove_member`` calls. It raises when a Secret cannot be deleted,
    and the caller then keeps the member: a removed member's token must
    not stay in the cluster."""
    rows = (
        db.query(McpCredential)
        .join(McpServer, McpCredential.server_id == McpServer.id)
        .filter(McpServer.org_id == org_id, McpCredential.user_id == user_id)
        .all()
    )
    store = get_secret_store()
    namespace = get_default_namespace()
    for row in rows:
        store.delete(namespace, row.secret_name)
        _value_cache.pop(row.secret_name, None)
        db.delete(row)
    db.flush()
    return len(rows)


def _cached_value(credential: McpCredential) -> str | None:
    hit = _value_cache.get(credential.secret_name)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = read_value(credential)
    if value is not None:
        _value_cache[credential.secret_name] = (
            time.monotonic() + VALUE_CACHE_SECONDS,
            value,
        )
    return value


def state(server: McpServer, user: CurrentUser) -> str:
    """NOT_NEEDED, SET or MISSING, from the rows alone (no Secret read):
    what the server list shows."""
    if server.credential_mode != MODE_PER_USER:
        return NOT_NEEDED
    return SET if user_credential(server, user.id) else MISSING


def forwarded_headers(alias: str, headers: dict[str, str]) -> dict[str, str]:
    """The proxy's per-call form of upstream headers for one server."""
    return {f"x-mcp-{alias}-{name.lower()}": v for name, v in headers.items()}


def resolve(server: McpServer, user: CurrentUser, alias: str) -> Resolved:
    """See the module docstring. ``alias`` is the server's name in the
    proxy, which the per-call header form needs."""
    if server.credential_mode != MODE_PER_USER:
        return Resolved(NOT_NEEDED, {})
    row = user_credential(server, user.id)
    value = _cached_value(row) if row is not None else None
    if value is None:
        return Resolved(MISSING, {})
    upstream = credential_headers(row.auth_type, row.auth_header, value)
    return Resolved(SET, forwarded_headers(alias, upstream))
