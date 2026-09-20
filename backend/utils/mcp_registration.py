"""The proxy side of an MCP server, for callers that have no user: the
poller that registers a deployed server when its pod is ready
(``api/mcp_instances.py``) next to the routes of ``api/mcp.py``.

The team and its permission list depend on the organization alone, so
these functions take an organization; the routes pass the caller's.
"""

import uuid

from sqlalchemy.orm import Session

from models.mcp_server import McpServer
from models.organization import Organization
from utils import mcp_credentials as creds
from utils.litellm import LiteLLMError, ensure_org_key
from utils.mcp_mock import MOCK_LITELLM_SERVER_ID


def organization(db: Session, org_id: uuid.UUID) -> Organization:
    return db.query(Organization).filter(Organization.id == org_id).one()


def team_id_for_org(litellm, db: Session, org_id: uuid.UUID) -> str | None:
    """The organization's LiteLLM team, created on first use. Call it
    before the first change of a request: ``ensure_org_key`` commits
    the session when it creates the team, and a row flushed before
    that would survive the rollback of a failed registration."""
    if litellm is None:
        return None
    org = organization(db, org_id)
    ensure_org_key(db, org)
    return org.litellm_team_id


def sync_team_for_org(
    litellm, db: Session, org_id: uuid.UUID, team_id: str | None
) -> None:
    """The organization team may use exactly its enabled servers."""
    if litellm is None or team_id is None:
        return
    ids = [
        s.litellm_server_id
        for s in db.query(McpServer)
        .filter(McpServer.org_id == org_id, McpServer.enabled.is_(True))
        .all()
        if s.litellm_server_id
        and s.litellm_server_id != MOCK_LITELLM_SERVER_ID
    ]
    litellm.set_team_mcp_servers(team_id, ids)


def server_body(
    alias: str,
    url: str,
    transport: str,
    credential=None,
    allowed_tools: list[str] | None = None,
    description: str | None = None,
    all_keys: bool = False,
    server_id: str | None = None,
) -> dict:
    """The proxy's ``NewMCPServerRequest``. ``transport`` is always
    sent: the proxy's default is ``sse``. The credential goes as static
    headers, which covers a bearer and a custom header alike.

    ``server_id`` is the caller's choice of the proxy's id (measured on
    v1.99.1: accepted, and a second registration with the same id is a
    400 "already exists"), which makes a registration that two replicas
    try safe."""
    body = {
        "server_name": alias,
        "alias": alias,
        "url": url,
        "transport": transport,
        "description": description,
        "allowed_tools": allowed_tools or [],
        "static_headers": {},
        # A platform server is for every organization's key (measured:
        # a team with no permission for it lists its tools). The relay
        # still names the servers of each request, so an organization
        # reaches only what it may see.
        "allow_all_keys": all_keys,
    }
    if server_id is not None:
        body["server_id"] = server_id
    if credential is not None:
        body["static_headers"] = creds.credential_headers(
            credential.auth_type, credential.auth_header, credential.value
        )
    return body


def register_once(litellm, body: dict) -> str:
    """Register with a chosen ``server_id``. "Already exists" means it
    is this server that exists: from another replica, or from an
    earlier tick whose later steps failed. What the proxy holds may be
    old by now (an admin can change the allow-list while there is no
    committed registration, and a PATCH skips the proxy then), and the
    allow-list is enforced in the proxy alone, so the body is sent
    again as an update."""
    try:
        return litellm.register_mcp_server(body)
    except LiteLLMError as e:
        if e.status == 400 and "already exists" in (e.text or ""):
            litellm.update_mcp_server(body["server_id"], body)
            return body["server_id"]
        raise


def unregister(litellm, server_id: str) -> None:
    """Remove a registration whose id the platform chose. The row may
    not know of it (a registration that was accepted and never
    committed), so it is always asked for, and "not there" is fine."""
    try:
        litellm.delete_mcp_server(server_id)
    except LiteLLMError as e:
        if e.status != 404 and "not found" not in (e.text or "").lower():
            raise
