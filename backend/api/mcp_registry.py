"""Import from the official MCP registry: the search behind the "From
the MCP registry" tab of the add dialog, and the probe behind its OAuth
hint. The browser never calls the registry itself: one egress point,
one place for the limits, and a fixture for the fast tier.

The model registry's search is for platform admins. This one is for
every writer, because every writer may add a personal remote server,
and the host is the operator's (``AIOPS_MCP_REGISTRY_URL``), not the
caller's. An entry only fills the add dialog: the URL rule and the
connection test come after it, as for a typed URL.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.chat import chat_mock_enabled
from auth.current_user import CurrentUser, require_writer
from db.database import get_db
from models.mcp_catalog import McpCatalogEntry
from models.mcp_server import McpServer
from paths import BACKEND_DIR
from registry import mcp_registry
from registry.entry import SourceError
from utils import mcp_oauth
from utils import mcp_scope as scopes
from utils.mcp import McpUrlError, validate_server_url

router = APIRouter()

FIXTURE = BACKEND_DIR / "test_fixtures" / "mcp_registry.json"


class McpRegistryRemoteSchema(BaseModel):
    url: str
    transport: str
    auth_type: str
    auth_header: str | None = None


class McpRegistryPreviewSchema(BaseModel):
    name: str
    title: str
    description: str | None = None
    version: str | None = None
    publisher: str
    website: str | None = None
    # A name the add dialog can start from (``utils.mcp.valid_name``).
    suggested_name: str
    remote: McpRegistryRemoteSchema | None = None
    remote_reason: str | None = None
    deployable: bool = False
    deployable_reason: str | None = None
    # A server the caller sees already has this URL.
    already_added: bool = False
    # For a platform admin: the deploy catalog has this entry.
    already_imported: bool = False


class OAuthProbeRequest(BaseModel):
    url: str


def _require_import() -> None:
    if mcp_registry.registry_url() is None:
        raise HTTPException(status_code=404, detail="Import is turned off")


def _entries(query: str, limit: int) -> list[mcp_registry.McpRegistryEntry]:
    if chat_mock_enabled():
        needle = query.strip().lower()
        recorded = json.loads(FIXTURE.read_text())["servers"]
        parsed = [mcp_registry.parse_server(item) for item in recorded]
        return [
            e
            for e in parsed
            if needle in e.name.lower()
            or needle in (e.description or "").lower()
        ][:limit]
    try:
        return mcp_registry.search(query, limit)
    except SourceError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


def _same(url: str) -> str:
    return url.strip().rstrip("/").lower()


@router.get(
    "/v1alpha1/mcp/registry/search",
    response_model=list[McpRegistryPreviewSchema],
)
async def search_mcp_registry(
    q: str = Query("", max_length=mcp_registry.MAX_QUERY),
    limit: int = Query(20, ge=1, le=mcp_registry.MAX_LIMIT),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    _require_import()
    entries = await asyncio.to_thread(_entries, q, limit)
    # Among what the caller sees only: never another member's own.
    mine = {
        _same(url)
        for (url,) in db.query(McpServer.url)
        .filter(scopes.visible(user))
        .all()
    }
    imported = (
        {
            source_id
            for (source_id,) in db.query(McpCatalogEntry.source_id)
            .filter(McpCatalogEntry.source == mcp_registry.SOURCE)
            .all()
        }
        if user.is_platform_admin
        else set()
    )
    return [
        McpRegistryPreviewSchema(
            name=e.name,
            title=e.title,
            description=e.description,
            version=e.version,
            publisher=e.publisher,
            website=e.website,
            suggested_name=mcp_registry.catalog_slug(e.name),
            remote=McpRegistryRemoteSchema(**e.remote.__dict__)
            if e.remote
            else None,
            remote_reason=e.remote_reason,
            deployable=e.deployable is not None,
            deployable_reason=e.deployable_reason,
            already_added=bool(e.remote and _same(e.remote.url) in mine),
            already_imported=e.name in imported,
        )
        for e in entries
    ]


@router.post("/v1alpha1/mcp/servers/oauth-probe")
def oauth_probe(
    body: OAuthProbeRequest,
    user: CurrentUser = Depends(require_writer),
):
    """After a connection test that the server refused: does it offer
    an OAuth sign-in? Never an error: the dialog shows a hint or not."""
    if chat_mock_enabled():
        return {"oauth": "oauth" in body.url}
    try:
        url = validate_server_url(body.url)
    except McpUrlError:
        return {"oauth": False}
    return {"oauth": mcp_oauth.probe(url)}
