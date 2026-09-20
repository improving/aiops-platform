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

The endpoint that serves the tools, ``/v1alpha1/mcp``, is
``api/mcp_endpoint.py``; it takes the LiteLLM client and the organization
key through this module (``litellm_client``, ``org_key``), so a test
patches them here for both.

``AIOPS_CHAT_MOCK=true`` mocks discovery and registration
(``utils/mcp_mock.py``) for the Playwright fast tier.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from api.chat import chat_mock_enabled
from auth.current_user import (
    CurrentUser,
    get_current_user,
    require_writer,
)
from db.database import get_db
from logger import setup_logger
from models.mcp_server import McpOAuthState, McpServer
from models.organization import Organization
from schemas.mcp import (
    McpCredentialInput,
    McpDiscoverRequest,
    McpOAuthCallbackRequest,
    McpOwnCredentialRequest,
    McpServerCreateRequest,
    McpServerSchema,
    McpServerUpdateRequest,
    McpToolSchema,
)
from utils import genid, mcp_oauth
from utils import mcp_credentials as creds
from utils import mcp_registration as registration
from utils import mcp_scope as scopes
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
from utils.mcp_mock import (
    MOCK_LITELLM_SERVER_ID,
    MOCK_OAUTH_CODE,
    MOCK_TOOLS,
    mock_oauth_metadata,
)

router = APIRouter()
logger = setup_logger(__name__)

STATUS_CONNECTED = "connected"
STATUS_UNREACHABLE = "unreachable"


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
    # Not visible reads like not there: a member learns nothing about
    # another member's personal server or another organization's.
    if server is None or not scopes.can_see(user, server):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


def _find_to_change(
    db: Session, id: uuid.UUID, user: CurrentUser
) -> McpServer:
    server = _find(db, id, user)
    if not scopes.can_change(user, server):
        raise HTTPException(
            status_code=403,
            detail="Only "
            + {
                scopes.SCOPE_PLATFORM: "a platform admin",
                scopes.SCOPE_PERSONAL: "its owner",
                scopes.SCOPE_ORGANIZATION: "an organization admin",
            }[scopes.scope_of(server)]
            + " can change this MCP server",
        )
    return server


def _aware(value: datetime | None) -> datetime | None:
    """The rows hold naive server-local times (``datetime.now()``). Sent
    like that, a browser reads them in ITS zone: a server checked a
    minute ago read "6 h" in IST. With the server's offset they say
    what they mean."""
    return value.astimezone() if value is not None else None


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
        credential_set_at=_aware(shared.updated_at)
        if shared is not None and scopes.can_change(user, server)
        else None,
        credential_header=_user_header(server),
        credential_help_url=server.credential_help_url,
        oauth=creds.is_oauth(server),
        sign_in_host=urlsplit(
            (server.oauth or {}).get("authorization_endpoint", "")
        ).hostname
        if creds.is_oauth(server)
        else None,
        allowed_tools=server.allowed_tools,
        approval=server.approval,
        enabled=server.enabled,
        status=server.status,
        checked_at=_aware(server.checked_at),
        tools=[McpToolSchema(**t) for t in server.tools_cache or []],
        tool_prefix=litellm_alias(server.id, server.name) + TOOL_SEPARATOR,
        scope=scopes.scope_of(server),
        can_change=scopes.can_change(user, server),
        deploy=_deploy_block(server),
    )


def _deployed():
    """The deployed-server side (``api/mcp_instances.py`` imports this
    module, so it is taken at call time)."""
    from api import mcp_instances

    return mcp_instances


def _deploy_block(server: McpServer):
    if server.instance is None:
        return None
    return _deployed().deploy_block(server, server.instance)


def _user_header(server: McpServer) -> str | None:
    if server.credential_mode != creds.MODE_PER_USER or creds.is_oauth(server):
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


def _owners_mode() -> str:
    """A personal server never has a shared credential. The proxy keeps
    a shared one as ``static_headers``, and the server is in the
    organization's team (the relay calls with the organization's key),
    so any key of that team would call with the owner's value. As the
    owner's own it travels with their calls only and the proxy never
    holds it."""
    return creds.MODE_PER_USER


@dataclass(frozen=True)
class _OAuthSetup:
    # What the row keeps (no secret), and the client secret apart.
    public: dict
    client_secret: str | None


def _oauth_setup(url: str, given) -> _OAuthSetup:
    """Discovery and, when the authorization server offers it, client
    registration; else the client the admin made there. 400 with the
    reason when the server cannot be signed in to."""
    if chat_mock_enabled():
        return _OAuthSetup(mock_oauth_metadata(), None)
    try:
        mcp_oauth.redirect_uri()
        metadata = mcp_oauth.discover(url, allow_hosts=given.allow_hosts)
        if given.client_id:
            client_id, client_secret = given.client_id, given.client_secret
        else:
            client_id, client_secret = mcp_oauth.register_client(metadata)
    except mcp_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=e.detail) from e
    return _OAuthSetup(
        {
            "issuer": metadata["issuer"],
            "authorization_endpoint": metadata["authorization_endpoint"],
            "token_endpoint": metadata["token_endpoint"],
            "client_id": client_id,
            "scopes": given.scopes or [],
            "iss_required": metadata["iss_required"],
            "token_auth": mcp_oauth.TOKEN_AUTH_POST
            if client_secret
            else mcp_oauth.TOKEN_AUTH_NONE,
        },
        client_secret,
    )


def _name_taken(db: Session, user: CurrentUser, name: str, scope: str) -> bool:
    """A name selects a server on the endpoint (``X-Mcp-Servers``). A
    personal server's name is free among everything its owner sees. An
    organization's or the platform's is free among the shared servers
    only: a member's personal server neither blocks the name for an
    admin nor shows them that it exists, and where both are visible the
    member's own wins (``scopes.by_name``). The partial unique indexes
    of the table say the same."""
    if scope == scopes.SCOPE_PERSONAL:
        among = scopes.visible(user)
    else:
        among = or_(
            McpServer.org_id.is_(None),
            and_(
                McpServer.org_id == user.org_id,
                McpServer.owner_id.is_(None),
            ),
        )
    return (
        db.query(McpServer.id).filter(among, McpServer.name == name).first()
        is not None
    )


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


_litellm_server = registration.server_body


def _own_credential(
    server: McpServer, user: CurrentUser, db: Session | None = None
) -> McpCredentialInput | None:
    """The caller's own credential on a per_user server, for a
    connection test on their behalf; None when they have none."""
    row = creds.user_credential(server, user.id)
    if row is None:
        return None
    if creds.is_oauth(server):
        # With the session, a sign-in that has ended also loses its row.
        value = creds.oauth_access_token(db, server, row)
    else:
        value = creds.read_value(row)
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
    registration.sync_team_for_org(litellm, db, user.org_id, team_id)


@router.post(
    "/v1alpha1/mcp/servers/discover", response_model=list[McpToolSchema]
)
def discover(
    body: McpDiscoverRequest,
    user: CurrentUser = Depends(require_writer),
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
        .options(joinedload(McpServer.instance))
        .filter(scopes.visible(user))
        .order_by(McpServer.name)
        .all()
    )
    if chat_mock_enabled():
        # No cluster and no poller: a read moves a deployed server on.
        for server in servers:
            if server.instance is not None:
                _deployed().mock_advance(db, server.instance)
    return [_response(s, user) for s in servers]


@router.post(
    "/v1alpha1/mcp/servers", response_model=McpServerSchema, status_code=201
)
def create_server(
    body: McpServerCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
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
    if not scopes.can_create(user, body.scope):
        raise HTTPException(
            status_code=403,
            detail={
                scopes.SCOPE_PLATFORM: "Only a platform admin adds a server "
                "for every organization",
                scopes.SCOPE_ORGANIZATION: "Only an organization admin adds a "
                "server for the organization; add one for yourself",
            }.get(body.scope, "You cannot add MCP servers"),
        )
    if _name_taken(db, user, body.name, body.scope):
        raise HTTPException(
            status_code=409, detail=f"MCP server '{body.name}' already exists"
        )
    by_sign_in = body.oauth is not None
    if by_sign_in:
        # Each member signs in: a per_user server whose values arrive
        # by OAuth. Nobody has a token yet, so there is no connection
        # test and no tool list until the first member has signed in.
        mode = creds.MODE_PER_USER
        oauth = _oauth_setup(url, body.oauth)
    else:
        mode = _requested_mode(body.credential_mode, body.credential)
        oauth = None
    if body.scope == scopes.SCOPE_PERSONAL and mode == creds.MODE_SHARED:
        mode = _owners_mode()
    per_user = mode == creds.MODE_PER_USER
    litellm = _require_litellm()
    try:
        team_id = _team_id(litellm, db, user)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    server = McpServer(
        id=genid.uuid4(),
        org_id=None if body.scope == scopes.SCOPE_PLATFORM else user.org_id,
        owner_id=user.id if body.scope == scopes.SCOPE_PERSONAL else None,
        name=body.name,
        description=body.description,
        source="remote",
        url=url,
        transport=body.transport,
        credential_mode=mode,
        user_auth_type=creds.AUTH_OAUTH
        if by_sign_in
        else (body.credential.auth_type if per_user else None),
        user_auth_header=body.credential.auth_header
        if per_user and not by_sign_in
        else None,
        oauth=oauth.public if oauth else None,
        credential_help_url=body.credential_help_url,
        allowed_tools=body.allowed_tools,
        approval=body.approval,
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

    if by_sign_in:
        if oauth.client_secret:
            creds.store_oauth_client_secret(server, oauth.client_secret)
    elif per_user:
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
        server.tools_cache = (
            []
            if by_sign_in
            else _discover(litellm, url, body.transport, body.credential)
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
                    all_keys=body.scope == scopes.SCOPE_PLATFORM,
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
    personal = server.owner_id is not None
    if personal and (
        mode == creds.MODE_SHARED
        or (mode is None and body.credential is not None)
    ):
        mode = _owners_mode()
    if mode is None:
        if body.remove_credential:
            mode = creds.MODE_NONE
        elif body.credential is None:
            return current
        else:
            mode = creds.MODE_SHARED
        if current == creds.MODE_PER_USER and not personal:
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
        and not personal  # the owner's is the only one there is
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
    user: CurrentUser = Depends(require_writer),
):
    server = _find_to_change(db, id, user)
    litellm = _require_litellm()
    _validate_credential(body.credential)
    if server.instance is not None and (
        body.credential is not None
        or body.credential_mode is not None
        or body.remove_credential
        or body.transport is not None
        or (body.url is not None and body.url != server.url)
    ):
        raise HTTPException(
            status_code=409,
            detail="The platform runs this server: its address and its "
            "credential are the platform's. Change its settings instead",
        )
    if creds.is_oauth(server) and (
        body.credential is not None
        or body.credential_mode is not None
        or body.remove_credential
        or (body.url is not None and body.url != server.url)
    ):
        # The client, the endpoints and every member's tokens belong to
        # this URL and this kind of sign-in; a half-changed row would
        # keep them and mean something else.
        raise HTTPException(
            status_code=409,
            detail="Members sign in to this server with OAuth, so its URL "
            "and credential cannot change. Delete it and add it again",
        )
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
    if body.approval is not None:
        server.approval = body.approval

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
                    all_keys=server.org_id is None,
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
    user: CurrentUser = Depends(require_writer),
):
    """Connect again and replace the tool list. A failure keeps the
    last known list and marks the server unreachable; it is an answer,
    not an error."""
    server = _find_to_change(db, id, user)
    litellm = _require_litellm()
    if server.instance is not None and not server.instance.ready:
        # A check of a pod that is starting would only write a wrong
        # "unreachable"; the poller lists the tools when it is ready.
        raise HTTPException(
            status_code=409, detail="This server is not running yet"
        )
    if server.credential_mode == creds.MODE_PER_USER:
        credential = _own_credential(server, user, db)
        if credential is None:
            # A check with no credential fails, and "unreachable" would
            # take the server away from every member who has one.
            raise HTTPException(
                status_code=409,
                detail="Sign in to this server first"
                if creds.is_oauth(server)
                else "Connect your own credential to this server first",
            )
    else:
        credential = _stored_credential(server)
    try:
        server.tools_cache = _discover(
            litellm,
            server.url,
            server.transport,
            credential,
        )
        server.status = STATUS_CONNECTED
    except LiteLLMError as e:
        logger.info("MCP server %s is unreachable: %s", server.name, e)
        server.status = STATUS_UNREACHABLE
    server.checked_at = datetime.now()
    db.commit()
    db.refresh(server)
    return _response(server, user)


def _require_person(user: CurrentUser) -> None:
    """A sign-in belongs to a person in a browser: not to a personal
    token, not to a service account."""
    if not user.is_browser_session:
        raise HTTPException(
            status_code=409, detail="Sign in through the platform's UI"
        )


@router.post("/v1alpha1/mcp/servers/{id}/oauth/start")
def oauth_start(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    """Where the member's browser goes to sign in. The ``state`` that
    comes back is kept hashed, with the PKCE verifier, for this member
    and this server, for ten minutes and one use."""
    _require_person(user)
    server = _find(db, id, user)
    if not creds.is_oauth(server) or not server.oauth:
        raise HTTPException(
            status_code=409, detail="Nobody signs in to this server"
        )
    state, state_hash = mcp_oauth.new_state()
    verifier = mcp_oauth.new_verifier()
    db.query(McpOAuthState).filter(
        McpOAuthState.created_at
        < datetime.now() - timedelta(seconds=mcp_oauth.STATE_TTL_SECONDS)
    ).delete()
    db.add(
        McpOAuthState(
            state_hash=state_hash,
            server_id=server.id,
            user_id=user.id,
            code_verifier=verifier,
        )
    )
    db.commit()
    try:
        if chat_mock_enabled():
            url = (
                f"{mcp_oauth.redirect_uri()}?code={MOCK_OAUTH_CODE}"
                f"&state={state}"
            )
        else:
            url = mcp_oauth.authorization_url(
                server.oauth, server.url, state, verifier
            )
    except mcp_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=e.detail) from e
    return {"authorization_url": url}


@router.post("/v1alpha1/mcp/oauth/callback", response_model=McpServerSchema)
def oauth_callback(
    body: McpOAuthCallbackRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    """The UI's callback page posts what the authorization server sent
    back. The state must be one this member started, unused and not
    older than ten minutes; then the code becomes the member's tokens."""
    _require_person(user)
    started = db.get(McpOAuthState, mcp_oauth.hash_state(body.state))
    # One answer for unknown, used, expired and somebody else's: a
    # caller learns nothing about the states of other members.
    refused = HTTPException(
        status_code=400,
        detail="This sign-in has expired or was not started here; start again",
    )
    if started is None:
        raise refused
    expired = datetime.now() - started.created_at > timedelta(
        seconds=mcp_oauth.STATE_TTL_SECONDS
    )
    mine = started.user_id == user.id
    verifier, server_id = started.code_verifier, started.server_id
    if mine:
        db.delete(started)  # single use, whatever happens next
        db.commit()
    if not mine or expired:
        raise refused
    server = _find(db, server_id, user)
    if not creds.is_oauth(server):
        raise refused
    try:
        if chat_mock_enabled():
            if body.code != MOCK_OAUTH_CODE:
                raise mcp_oauth.OAuthError(
                    "The mock accepts its own code only"
                )
            tokens = mcp_oauth.Tokens(
                "mock-access-token", "mock-refresh-token", time.time() + 3600
            )
        else:
            mcp_oauth.check_issuer(server.oauth or {}, body.iss)
            tokens = mcp_oauth.exchange_code(
                server.oauth,
                creds.read_oauth_client_secret(server),
                server.url,
                body.code,
                verifier,
            )
    except mcp_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=e.detail) from e
    creds.store_oauth_tokens(db, server, user.id, tokens)
    # The first member in lists the tools: nobody could before.
    if not server.tools_cache:
        try:
            server.tools_cache = _discover(
                None if chat_mock_enabled() else litellm_client(),
                server.url,
                server.transport,
                McpCredentialInput(
                    auth_type=creds.AUTH_BEARER, value=tokens.access_token
                ),
            )
            server.status = STATUS_CONNECTED
            server.checked_at = datetime.now()
        except LiteLLMError as e:
            logger.info(
                "Could not list the tools of %s yet: %s", server.name, e
            )
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
    if creds.is_oauth(server):
        raise HTTPException(
            status_code=409,
            detail="This server takes no pasted credential: sign in to it",
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
    user: CurrentUser = Depends(require_writer),
):
    """The proxy first: it holds a copy of a shared credential, and once
    the row is gone nothing would ever retry. When it refuses, the
    delete fails (502) and everything stays. Without a configured proxy
    there is no copy, and the Secrets and the row go."""
    server = _find_to_change(db, id, user)
    litellm = None if chat_mock_enabled() else litellm_client()
    registered = server.litellm_server_id
    deployed = server.instance is not None
    if litellm is not None and (registered or deployed):
        try:
            team_id = _team_id(litellm, db, user)
            if deployed:
                # Its id in the proxy is the row's own, whether or not
                # the row knows of a registration yet.
                registration.unregister(litellm, str(server.id))
            else:
                litellm.delete_mcp_server(registered)
        except LiteLLMError as e:
            raise HTTPException(
                status_code=502,
                detail=f"The server stays: the proxy did not remove it ({e})",
            ) from e
    else:
        team_id = None
    if server.instance is not None:
        # The true state first: a delete that stops at the uninstall
        # leaves a disabled server that the proxy does not know (so the
        # poller does not register it again), and a second Delete
        # finishes the work.
        server.litellm_server_id = None
        server.status = STATUS_UNREACHABLE
        server.enabled = False
        server.instance.registered_at = None
        db.commit()
        _deployed().remove_workload(db, server)
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
