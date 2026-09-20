"""``/v1alpha1/mcp``: the one door to the tools of an organization's MCP
servers, for the chat playground, IDEs, SDKs and Langflow (MCP over
streamable HTTP). It authenticates the caller (session or personal
token), refuses viewers (a tool can change data), picks the servers,
resolves the caller's credentials (``utils/mcp_credentials.py``) and
relays to LiteLLM ``/mcp`` with the organization's key
(``utils/mcp_relay.py``). LiteLLM's own endpoint stays inside the
cluster. The registry is ``api/mcp.py``; the LiteLLM client and the
organization key are taken through that module, so a test patches them
in one place.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from api import mcp as registry
from api.chat import chat_mock_enabled, user_key
from auth.current_user import CurrentUser, require_writer
from db.database import get_db
from logger import setup_logger
from models.mcp_server import McpServer
from utils import mcp_credentials as creds
from utils import mcp_instances
from utils import mcp_scope as scopes
from utils.litellm import LiteLLMError
from utils.mcp import litellm_alias
from utils.mcp_mock import mock_endpoint
from utils.mcp_relay import SERVERS_HEADER, LiteLLMUpstream, relay

router = APIRouter()
logger = setup_logger(__name__)

# An alias that names no server: LiteLLM answers an empty tool list.
NO_SERVERS = "none"


def _selected(
    db: Session, user: CurrentUser, requested: str | None
) -> list[McpServer]:
    """The servers of this request: every enabled one of the caller's
    organization, or the ``X-Mcp-Servers`` names among them. An unknown
    name is a 400, so a typo is not a silent empty tool list."""
    enabled = (
        db.query(McpServer)
        .options(joinedload(McpServer.instance))
        .filter(scopes.visible(user), McpServer.enabled.is_(True))
        .all()
    )
    if not requested or not requested.strip():
        # A deployed server whose pod does not serve is left out
        # (measured: one registered server that is down adds nine
        # seconds to every tools/list of the proxy).
        return [s for s in enabled if mcp_instances.usable(s, s.instance)]
    by_name = scopes.by_name(enabled)
    names = [n.strip() for n in requested.split(",") if n.strip()]
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or disabled MCP server: {', '.join(unknown)}",
        )
    down = [
        n
        for n in names
        if not mcp_instances.usable(by_name[n], by_name[n].instance)
    ]
    if down:
        raise HTTPException(
            status_code=409,
            detail=f"MCP server {', '.join(down)} is not running",
        )
    return [by_name[n] for n in names]


def _log_tool_call(user: CurrentUser, body: bytes | None) -> None:
    """Who called which tool, never with what: the audit log skips this
    path (one event per protocol message would drown it)."""
    if not body or b"tools/call" not in body:
        return
    try:
        message = json.loads(body)
    except ValueError:
        return
    if isinstance(message, dict) and message.get("method") == "tools/call":
        name = (message.get("params") or {}).get("name")
        logger.info("MCP tool call by %s: %s", user.email or user.sub, name)


@router.api_route("/v1alpha1/mcp", methods=["GET", "POST", "DELETE"])
async def mcp_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    # No server-to-client stream: the proxy would hold a GET open for as
    # long as the client stays, each one on a worker thread of the pool
    # that also runs every sync route, so some tens of idle IDE sessions
    # would stop the API. The protocol allows 405 here, and clients then
    # work with POST alone (the tools of a registry do not push events).
    if request.method == "GET":
        return Response(status_code=405, headers={"Allow": "POST, DELETE"})
    body = await request.body() if request.method == "POST" else None
    servers = _selected(db, user, request.headers.get(SERVERS_HEADER))
    _log_tool_call(user, body)
    if chat_mock_enabled():
        return mock_endpoint(
            request.method,
            body,
            [litellm_alias(s.id, s.name) for s in servers],
        )
    litellm = registry.litellm_client()
    if litellm is None:
        raise HTTPException(
            status_code=503,
            detail="MCP servers need the LiteLLM proxy, which is not configured",
        )
    explicit = bool((request.headers.get(SERVERS_HEADER) or "").strip())
    usable = []
    extra: dict[str, str] = {}
    for server in servers:
        alias = litellm_alias(server.id, server.name)
        resolved = await asyncio.to_thread(
            creds.resolve, server, user, alias, db
        )
        if resolved.state == creds.MISSING:
            # Asked for by name: say what is missing. Among "all the
            # servers" it is left out, and the others still work.
            if explicit:
                raise HTTPException(
                    status_code=409,
                    detail=f"Connect your own credential for {server.name} "
                    "first (MCP servers page, or the Tools section of Chat)",
                )
            continue
        usable.append(alias)
        extra.update(resolved.headers)
    try:
        key = await asyncio.to_thread(registry.org_key, db, user)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    upstream = LiteLLMUpstream(
        litellm, key, usable or [NO_SERVERS], extra, end_user=user_key(user)
    )
    return await asyncio.to_thread(
        relay, upstream, request.method, request.headers, body
    )
