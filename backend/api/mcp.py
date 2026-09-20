"""MCP servers: an organization admin registers a remote MCP server
(a URL and, optionally, one credential the organization shares), and
every member reaches the tools of every enabled server through one
endpoint, ``/v1alpha1/mcp`` (MCP over streamable HTTP).

The registry's write routes are plain ``def``: FastAPI runs them in its
thread pool. Between ``flush`` and ``commit`` a request holds SQLite's
write lock, and a second writer that waited for it on the event loop
would stop the first from ever reaching its commit (found by the
parallel Playwright workers: both answered 500 after the lock timeout).

Registration follows the hosted providers (``api/providers.py``): the
row, then the Secret, then LiteLLM (the server and the organization
team's permission for it), then the commit; a failure undoes the
earlier steps and answers 502. Members read servers without secrets;
only admins write.

``/v1alpha1/mcp`` is the one door for the chat playground, IDEs, SDKs
and Langflow. It authenticates the caller (session or personal token),
refuses viewers (a tool can change data), picks the servers, resolves
the caller's credentials (``utils/mcp_credentials.py``) and relays to
LiteLLM ``/mcp`` with the organization's key (``utils/mcp_relay.py``).
LiteLLM's own endpoint stays inside the cluster.

``AIOPS_CHAT_MOCK=true`` mocks discovery, registration and the endpoint
(one tool, ``echo``) for the Playwright fast tier.
"""

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.chat import chat_mock_enabled
from auth.current_user import (
    CurrentUser,
    get_current_user,
    require_admin,
    require_writer,
)
from auth.policy import authorize_read, org_scope
from auth.roles import ROLE_ADMIN
from db.database import get_db
from logger import setup_logger
from models.mcp_server import McpServer
from models.organization import Organization
from schemas.mcp import (
    McpCredentialInput,
    McpDiscoverRequest,
    McpOwnCredentialRequest,
    McpServerCreateRequest,
    McpServerSchema,
    McpServerUpdateRequest,
    McpToolSchema,
)
from utils import genid
from utils import mcp_credentials as creds
from utils.litellm import LiteLLMError, ensure_org_key
from utils.litellm import get_client as get_litellm_client
from utils.mcp import (
    TOOL_SEPARATOR,
    TRANSPORTS,
    McpUrlError,
    litellm_alias,
    tool_summary,
    valid_name,
    validate_server_url,
)
from utils.mcp_relay import SERVERS_HEADER, LiteLLMUpstream, relay

router = APIRouter()
logger = setup_logger(__name__)

STATUS_CONNECTED = "connected"
STATUS_UNREACHABLE = "unreachable"
MOCK_LITELLM_SERVER_ID = "mock"
MOCK_TOOLS = [
    {
        "name": "echo",
        "description": "Say it again",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        "annotations": {"readOnlyHint": True},
    }
]
# An alias that names no server: LiteLLM answers an empty tool list.
NO_SERVERS = "none"


def litellm_client():
    """The proxy client, or None when it is not configured. A seam of
    this module's own, so tests patch it here."""
    return get_litellm_client()


def _require_litellm():
    """None in mock mode; the client otherwise, or a 503."""
    if chat_mock_enabled():
        return None
    litellm = litellm_client()
    if litellm is None:
        raise HTTPException(
            status_code=503,
            detail="MCP servers need the LiteLLM proxy, which is not configured",
        )
    return litellm


def _organization(db: Session, user: CurrentUser) -> Organization:
    return db.query(Organization).filter(Organization.id == user.org_id).one()


def org_key(db: Session, user: CurrentUser) -> str:
    """The organization's LiteLLM key; creates the team on first use."""
    return ensure_org_key(db, _organization(db, user))


def _find(db: Session, id: uuid.UUID, user: CurrentUser) -> McpServer:
    server = db.query(McpServer).filter(McpServer.id == id).first()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    authorize_read(user, server, "MCP server")
    return server


def _response(server: McpServer, user: CurrentUser) -> McpServerSchema:
    shared = creds.shared_credential(server)
    return McpServerSchema(
        id=server.id,
        name=server.name,
        description=server.description,
        source=server.source,
        url=server.url,
        transport=server.transport,
        credential_mode=server.credential_mode,
        my_credential=creds.state(server, user),
        credential_set_at=shared.updated_at
        if shared is not None and user.role == ROLE_ADMIN
        else None,
        credential_header=_user_header(server),
        credential_help_url=server.credential_help_url,
        allowed_tools=server.allowed_tools,
        enabled=server.enabled,
        status=server.status,
        checked_at=server.checked_at,
        tools=[McpToolSchema(**t) for t in server.tools_cache or []],
        tool_prefix=litellm_alias(server.id, server.name) + TOOL_SEPARATOR,
    )


def _user_header(server: McpServer) -> str | None:
    if server.credential_mode != creds.MODE_PER_USER:
        return None
    if server.user_auth_type == creds.AUTH_HEADER:
        return server.user_auth_header
    return "Authorization"


def _requested_mode(
    mode: str | None, credential: McpCredentialInput | None
) -> str:
    """The mode of a create: asked for, else from the credential."""
    if mode is None:
        return creds.MODE_SHARED if credential else creds.MODE_NONE
    if mode not in creds.CREDENTIAL_MODES:
        raise HTTPException(
            status_code=400,
            detail="credential_mode must be one of "
            + ", ".join(creds.CREDENTIAL_MODES),
        )
    if mode != creds.MODE_NONE and credential is None:
        raise HTTPException(
            status_code=400,
            detail="This credential mode needs a credential: the shared "
            "one, or your own for a server where each member brings theirs",
        )
    return mode


def _validated_url(url: str) -> str:
    try:
        return validate_server_url(url, resolve=not chat_mock_enabled())
    except McpUrlError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _validate_transport(transport: str) -> None:
    if transport not in TRANSPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"transport must be one of {', '.join(TRANSPORTS)}",
        )


def _validate_credential(credential: McpCredentialInput | None) -> None:
    if credential is None:
        return
    if credential.auth_type not in creds.AUTH_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"auth_type must be one of {', '.join(creds.AUTH_TYPES)}",
        )
    if (
        credential.auth_type == creds.AUTH_HEADER
        and not credential.auth_header
    ):
        raise HTTPException(
            status_code=400,
            detail="auth_header is required for a custom header",
        )


def _litellm_server(
    alias: str,
    url: str,
    transport: str,
    credential: McpCredentialInput | None,
    allowed_tools: list[str] | None,
    description: str | None = None,
) -> dict:
    """The proxy's ``NewMCPServerRequest``. ``transport`` is always
    sent: the proxy's default is ``sse``. The credential goes as static
    headers, which covers a bearer and a custom header alike."""
    body = {
        "server_name": alias,
        "alias": alias,
        "url": url,
        "transport": transport,
        "description": description,
        "allowed_tools": allowed_tools or [],
        "static_headers": {},
    }
    if credential is not None:
        body["static_headers"] = creds.credential_headers(
            credential.auth_type, credential.auth_header, credential.value
        )
    return body


def _own_credential(
    server: McpServer, user: CurrentUser
) -> McpCredentialInput | None:
    """The caller's own credential on a per_user server, for a
    connection test on their behalf; None when they have none."""
    row = creds.user_credential(server, user.id)
    value = creds.read_value(row) if row is not None else None
    if value is None:
        return None
    return McpCredentialInput(
        auth_type=row.auth_type, auth_header=row.auth_header, value=value
    )


def _stored_credential(server: McpServer) -> McpCredentialInput | None:
    """The shared credential as the proxy needs it, read back from the
    Secret (an update re-sends the whole server). A per_user server has
    none: the proxy gets each caller's value with the call."""
    row = creds.shared_credential(server)
    if row is None:
        return None
    value = creds.read_value(row)
    if value is None:
        raise HTTPException(
            status_code=502,
            detail="The server's credential Secret is missing; set the credential again",
        )
    return McpCredentialInput(
        auth_type=row.auth_type, auth_header=row.auth_header, value=value
    )


def _discover(
    litellm,
    url: str,
    transport: str,
    credential: McpCredentialInput | None,
) -> list[dict]:
    if litellm is None:
        return [tool_summary(t) for t in MOCK_TOOLS]
    tools = litellm.list_mcp_tools(
        _litellm_server("discover", url, transport, credential, None)
    )
    return [tool_summary(t) for t in tools]


def _team_id(litellm, db: Session, user: CurrentUser) -> str | None:
    """The organization's LiteLLM team, created on first use. Call it
    before the first change of a request: ``ensure_org_key`` commits
    the session when it creates the team, and a row flushed before
    that would survive the rollback of a failed registration."""
    if litellm is None:
        return None
    org_key(db, user)
    return _organization(db, user).litellm_team_id


def _sync_team(
    litellm, db: Session, user: CurrentUser, team_id: str | None
) -> None:
    """The organization team may use exactly its enabled servers."""
    if litellm is None or team_id is None:
        return
    ids = [
        s.litellm_server_id
        for s in db.query(McpServer)
        .filter(org_scope(McpServer, user), McpServer.enabled.is_(True))
        .all()
        if s.litellm_server_id
        and s.litellm_server_id != MOCK_LITELLM_SERVER_ID
    ]
    litellm.set_team_mcp_servers(team_id, ids)


@router.post(
    "/v1alpha1/mcp/servers/discover", response_model=list[McpToolSchema]
)
def discover(
    body: McpDiscoverRequest,
    user: CurrentUser = Depends(require_admin),
):
    """The preflight of the "Add MCP server" dialog, before a row
    exists: connect once and list the tools."""
    _validate_transport(body.transport)
    _validate_credential(body.credential)
    url = _validated_url(body.url)
    litellm = _require_litellm()
    try:
        return _discover(litellm, url, body.transport, body.credential)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1alpha1/mcp/servers", response_model=list[McpServerSchema])
async def list_servers(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    servers = (
        db.query(McpServer)
        .filter(org_scope(McpServer, user))
        .order_by(McpServer.name)
        .all()
    )
    return [_response(s, user) for s in servers]


@router.post(
    "/v1alpha1/mcp/servers", response_model=McpServerSchema, status_code=201
)
def create_server(
    body: McpServerCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    if not valid_name(body.name):
        raise HTTPException(
            status_code=400,
            detail="The name must be lower case letters, digits and _, "
            "start with a letter, and be at most 32 characters",
        )
    _validate_transport(body.transport)
    _validate_credential(body.credential)
    url = _validated_url(body.url)
    mode = _requested_mode(body.credential_mode, body.credential)
    per_user = mode == creds.MODE_PER_USER
    litellm = _require_litellm()
    try:
        team_id = _team_id(litellm, db, user)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    server = McpServer(
        id=genid.uuid4(),
        org_id=user.org_id,
        name=body.name,
        description=body.description,
        source="remote",
        url=url,
        transport=body.transport,
        credential_mode=mode,
        user_auth_type=body.credential.auth_type if per_user else None,
        user_auth_header=body.credential.auth_header if per_user else None,
        credential_help_url=body.credential_help_url,
        allowed_tools=body.allowed_tools,
        enabled=True,
    )
    db.add(server)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"MCP server '{body.name}' already exists"
        ) from None

    if per_user:
        # The admin's own, which the connection test below uses; the
        # proxy is registered without any, and gets each caller's value
        # with the call.
        creds.store_for_user(db, server, user.id, body.credential.value)
    elif mode == creds.MODE_SHARED:
        creds.store_shared(
            db,
            server,
            body.credential.auth_type,
            body.credential.auth_header,
            body.credential.value,
        )
    registered_credential = None if per_user else body.credential

    alias = litellm_alias(server.id, server.name)
    registered: str | None = None
    try:
        server.tools_cache = _discover(
            litellm, url, body.transport, body.credential
        )
        if litellm is None:
            server.litellm_server_id = MOCK_LITELLM_SERVER_ID
        else:
            registered = litellm.register_mcp_server(
                _litellm_server(
                    alias,
                    url,
                    body.transport,
                    registered_credential,
                    body.allowed_tools,
                    body.description,
                ),
            )
            server.litellm_server_id = registered
        server.status = STATUS_CONNECTED
        server.checked_at = datetime.now()
        db.flush()
        _sync_team(litellm, db, user, team_id)
    except LiteLLMError as e:
        if registered is not None:
            try:
                litellm.delete_mcp_server(registered)
            except LiteLLMError:
                logger.exception("Could not undo MCP server %s", registered)
        creds.delete_all(server)
        db.rollback()
        raise HTTPException(status_code=502, detail=str(e)) from e

    db.commit()
    db.refresh(server)
    return _response(server, user)


def _target_mode(server: McpServer, body: McpServerUpdateRequest) -> str:
    """The credential mode the server has after this PATCH, said
    explicitly wherever a guess could delete members' credentials."""
    current = server.credential_mode
    mode = body.credential_mode
    if mode is not None and mode not in creds.CREDENTIAL_MODES:
        raise HTTPException(
            status_code=400,
            detail="credential_mode must be one of "
            + ", ".join(creds.CREDENTIAL_MODES),
        )
    if mode is None:
        if body.remove_credential:
            mode = creds.MODE_NONE
        elif body.credential is None:
            return current
        else:
            mode = creds.MODE_SHARED
        if current == creds.MODE_PER_USER:
            raise HTTPException(
                status_code=400,
                detail="Each member has their own credential on this "
                "server. Send credential_mode to change that: it deletes "
                "every member's credential. For your own, use PUT "
                ".../credential",
            )
    if mode == creds.MODE_NONE:
        return mode
    if body.credential is None and mode != current:
        raise HTTPException(
            status_code=400,
            detail="This credential mode needs a credential: the shared "
            "one, or your own for a server where each member brings theirs",
        )
    if (
        mode == current == creds.MODE_PER_USER
        and body.credential is not None
        and (
            body.credential.auth_type != server.user_auth_type
            or (body.credential.auth_header or None) != server.user_auth_header
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="The members' credentials have another header shape; "
            "change to a shared credential first",
        )
    return mode


def _apply_credential_change(
    db: Session,
    server: McpServer,
    user: CurrentUser,
    target: str,
    credential: McpCredentialInput | None,
) -> None:
    """The Secrets and rows of a PATCH, after the proxy accepted it. A
    change of mode leaves no credential of the other mode behind."""
    current = server.credential_mode
    if target == current and credential is None:
        return
    if target != current or target == creds.MODE_NONE:
        creds.delete_all(server)
        server.credentials.clear()
        db.flush()
    server.credential_mode = target
    if target == creds.MODE_PER_USER:
        server.user_auth_type = credential.auth_type
        server.user_auth_header = (
            credential.auth_header
            if credential.auth_type == creds.AUTH_HEADER
            else None
        )
        creds.store_for_user(db, server, user.id, credential.value)
        return
    server.user_auth_type = server.user_auth_header = None
    if target == creds.MODE_SHARED:
        creds.store_shared(
            db,
            server,
            credential.auth_type,
            credential.auth_header,
            credential.value,
        )


@router.patch("/v1alpha1/mcp/servers/{id}", response_model=McpServerSchema)
def update_server(
    id: uuid.UUID,
    body: McpServerUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    server = _find(db, id, user)
    litellm = _require_litellm()
    _validate_credential(body.credential)
    try:
        team_id = _team_id(litellm, db, user)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if body.transport is not None:
        _validate_transport(body.transport)
        server.transport = body.transport
    if body.url is not None:
        server.url = _validated_url(body.url)
    if body.description is not None:
        server.description = body.description
    if body.allow_all_tools:
        server.allowed_tools = None
    elif body.allowed_tools is not None:
        server.allowed_tools = body.allowed_tools
    if body.enabled is not None:
        server.enabled = body.enabled

    if body.credential_help_url is not None:
        server.credential_help_url = body.credential_help_url or None

    target = _target_mode(server, body)
    # What the proxy holds after this request: the shared credential,
    # or none (no credential at all, or each caller's own with the call).
    if target != creds.MODE_SHARED:
        registered = None
    elif body.credential is not None:
        registered = body.credential
    else:
        registered = _stored_credential(server)

    # The proxy first, the Secrets after it: a Secret that is deleted or
    # written over cannot be rolled back, and a failure of the proxy
    # must leave every credential as it was.
    try:
        if litellm is not None and server.litellm_server_id:
            litellm.update_mcp_server(
                server.litellm_server_id,
                _litellm_server(
                    litellm_alias(server.id, server.name),
                    server.url,
                    server.transport,
                    registered,
                    server.allowed_tools,
                    server.description,
                ),
            )
        db.flush()
        _sync_team(litellm, db, user, team_id)
    except LiteLLMError as e:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(e)) from e
    _apply_credential_change(db, server, user, target, body.credential)
    db.commit()
    db.refresh(server)
    return _response(server, user)


@router.post(
    "/v1alpha1/mcp/servers/{id}/refresh", response_model=McpServerSchema
)
def refresh_server(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """Connect again and replace the tool list. A failure keeps the
    last known list and marks the server unreachable; it is an answer,
    not an error."""
    server = _find(db, id, user)
    litellm = _require_litellm()
    try:
        server.tools_cache = _discover(
            litellm,
            server.url,
            server.transport,
            _own_credential(server, user)
            if server.credential_mode == creds.MODE_PER_USER
            else _stored_credential(server),
        )
        server.status = STATUS_CONNECTED
    except LiteLLMError as e:
        logger.info("MCP server %s is unreachable: %s", server.name, e)
        server.status = STATUS_UNREACHABLE
    server.checked_at = datetime.now()
    db.commit()
    db.refresh(server)
    return _response(server, user)


@router.put(
    "/v1alpha1/mcp/servers/{id}/credential", response_model=McpServerSchema
)
def set_own_credential(
    id: uuid.UUID,
    body: McpOwnCredentialRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    """A member's own credential for a server where each member brings
    theirs. The value is tried against the server first (400 when the
    server refuses it), stored in a Secret of the member's own, and
    never returned."""
    server = _find(db, id, user)
    if server.credential_mode != creds.MODE_PER_USER:
        raise HTTPException(
            status_code=409,
            detail="This server does not take a credential of your own",
        )
    litellm = _require_litellm()
    attempt = McpCredentialInput(
        auth_type=server.user_auth_type or creds.AUTH_BEARER,
        auth_header=server.user_auth_header,
        value=body.value,
    )
    try:
        _discover(litellm, server.url, server.transport, attempt)
    except LiteLLMError as e:
        raise HTTPException(
            status_code=400,
            detail=f"The server did not accept this credential. {e}",
        ) from e
    creds.store_for_user(db, server, user.id, body.value)
    db.commit()
    db.refresh(server)
    return _response(server, user)


@router.delete(
    "/v1alpha1/mcp/servers/{id}/credential", response_model=McpServerSchema
)
def delete_own_credential(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    server = _find(db, id, user)
    creds.delete_for_user_on_server(db, server, user.id)
    db.commit()
    db.refresh(server)
    return _response(server, user)


@router.delete("/v1alpha1/mcp/servers/{id}", status_code=204)
def delete_server(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """The proxy first: it holds a copy of a shared credential, and once
    the row is gone nothing would ever retry. When it refuses, the
    delete fails (502) and everything stays. Without a configured proxy
    there is no copy, and the Secrets and the row go."""
    server = _find(db, id, user)
    litellm = None if chat_mock_enabled() else litellm_client()
    registered = server.litellm_server_id
    if litellm is not None and registered:
        try:
            team_id = _team_id(litellm, db, user)
            litellm.delete_mcp_server(registered)
        except LiteLLMError as e:
            raise HTTPException(
                status_code=502,
                detail=f"The server stays: the proxy did not remove it ({e})",
            ) from e
    else:
        team_id = None
    creds.delete_all(server)
    db.delete(server)
    db.flush()
    try:
        _sync_team(litellm, db, user, team_id)
    except LiteLLMError:
        # The server is gone from the proxy; a stale id in the team's
        # list names nothing, and the next write syncs the list again.
        logger.exception("Could not sync the team after deleting %s", id)
    db.commit()
    return Response(status_code=204)


# --- the endpoint -------------------------------------------------------


def _selected(
    db: Session, user: CurrentUser, requested: str | None
) -> list[McpServer]:
    """The servers of this request: every enabled one of the caller's
    organization, or the ``X-Mcp-Servers`` names among them. An unknown
    name is a 400, so a typo is not a silent empty tool list."""
    enabled = (
        db.query(McpServer)
        .filter(org_scope(McpServer, user), McpServer.enabled.is_(True))
        .all()
    )
    if not requested or not requested.strip():
        return enabled
    by_name = {s.name: s for s in enabled}
    names = [n.strip() for n in requested.split(",") if n.strip()]
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or disabled MCP server: {', '.join(unknown)}",
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


def _jsonrpc(id, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id, "result": result})


def _mock_endpoint(method: str, body: bytes | None) -> Response:
    """A stateless MCP server with one tool, for the fast tier: the
    chat route's MCP client connects to it as to the real endpoint."""
    if method != "POST":
        return Response(status_code=405, headers={"Allow": "POST"})
    try:
        message = json.loads(body or b"")
    except ValueError:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
            status_code=400,
        )
    rpc = message.get("method", "")
    if "id" not in message:
        return Response(status_code=202)
    params = message.get("params") or {}
    if rpc == "initialize":
        return _jsonrpc(
            message["id"],
            {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aiops-mock-mcp", "version": "1"},
            },
        )
    if rpc == "ping":
        return _jsonrpc(message["id"], {})
    if rpc == "tools/list":
        return _jsonrpc(message["id"], {"tools": MOCK_TOOLS})
    if rpc == "tools/call":
        text = str((params.get("arguments") or {}).get("message", ""))
        return _jsonrpc(
            message["id"],
            {"content": [{"type": "text", "text": text}], "isError": False},
        )
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": f"Method not found: {rpc}"},
        }
    )


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
        return _mock_endpoint(request.method, body)
    litellm = litellm_client()
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
        resolved = await asyncio.to_thread(creds.resolve, server, user, alias)
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
        key = await asyncio.to_thread(org_key, db, user)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    upstream = LiteLLMUpstream(litellm, key, usable or [NO_SERVERS], extra)
    return await asyncio.to_thread(
        relay, upstream, request.method, request.headers, body
    )
