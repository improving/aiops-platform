"""The catalog of MCP servers the platform can deploy.

Members and organization admins see the ``published`` entries. A
platform admin also sees drafts, imports an entry of the official MCP
registry as a draft, reviews it (image, arguments, settings, egress)
and publishes it. A draft is an image that nobody has read yet, which is
why, unlike the model registry, an organization admin does not see it.

What runs is what was reviewed: a sync that changes the image, the
arguments, the port, the path or the settings sends a published entry
back to ``draft``.
"""

import asyncio
import json
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.chat import chat_mock_enabled
from auth.current_user import (
    CurrentUser,
    get_current_user,
    require_platform_admin,
)
from db.database import get_db
from models.mcp_catalog import (
    CATALOG_STATUSES,
    EGRESS_MODES,
    EGRESS_PUBLIC,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    McpCatalogEntry,
)
from models.mcp_instance import McpInstance
from paths import BACKEND_DIR
from registry import mcp_registry
from registry.entry import SourceError
from schemas.mcp_deploy import (
    McpCatalogEntrySchema,
    McpCatalogImportRequest,
    McpCatalogReviewSchema,
    McpCatalogUpdateRequest,
)
from utils import genid
from utils.mcp import valid_name
from utils.mcp_catalog_settings import SettingsError, normal_setting
from utils.render_guard import refuse_line_breaks

router = APIRouter()

CHART_REPO = "https://infracloudio.github.io/charts"
CHART_NAME = "mcp-server"
_PATH = re.compile(r"^/[^\s?#]*$")
# What a sync may move, and what sends a published entry back to draft.
_RUNS = ("image", "tag", "args", "port", "path", "settings")
FIXTURE = BACKEND_DIR / "test_fixtures" / "mcp_registry.json"


def _find(db: Session, id: uuid.UUID) -> McpCatalogEntry:
    row = db.get(McpCatalogEntry, id)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    return row


def _in_use(db: Session, row: McpCatalogEntry) -> int:
    return (
        db.query(McpInstance).filter(McpInstance.catalog_id == row.id).count()
    )


def _review(db: Session, row: McpCatalogEntry) -> McpCatalogReviewSchema:
    data = McpCatalogEntrySchema.model_validate(row).model_dump()
    return McpCatalogReviewSchema(
        **data,
        command=row.command or [],
        args=row.args or [],
        notes=row.notes or [],
        in_use=_in_use(db, row),
    )


def _fetch(name: str, version: str | None) -> mcp_registry.McpRegistryEntry:
    """Always on the server: what a browser sends is never the entry."""
    if chat_mock_enabled():
        for item in json.loads(FIXTURE.read_text())["servers"]:
            if item["server"]["name"] == name:
                return mcp_registry.parse_server(item)
        raise HTTPException(status_code=404, detail=f"Unknown entry: {name}")
    try:
        return mcp_registry.fetch(name, version or "latest")
    except SourceError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


def _checked_runs(values: dict) -> dict:
    """What decides what runs, checked wherever it enters: at import, at
    a sync and at a review's PATCH, not first when Helm renders it."""
    try:
        refuse_line_breaks(
            {
                k: values[k]
                for k in ("image", "tag", "args", "path")
                if k in values
            }
        )
        if "settings" in values:
            values["settings"] = [
                normal_setting(s) for s in values["settings"]
            ]
            refuse_line_breaks(values["settings"])
    except (ValueError, SettingsError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if "path" in values and not _PATH.match(values["path"]):
        raise HTTPException(
            status_code=422,
            detail="The path starts with / and has no ?, # or white space",
        )
    if "args" in values and not all(
        isinstance(a, str) for a in values["args"]
    ):
        raise HTTPException(status_code=422, detail="Arguments are text")
    return values


def _runs_of(form: mcp_registry.DeployableForm) -> dict:
    return _checked_runs(
        {
            "image": form.image,
            "tag": form.tag,
            "args": list(form.args),
            "port": form.port,
            "path": form.path,
            "settings": list(form.settings),
        }
    )


@router.get(
    "/v1alpha1/mcp/catalog", response_model=list[McpCatalogEntrySchema]
)
def list_catalog(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    query = db.query(McpCatalogEntry)
    if not user.is_platform_admin:
        query = query.filter(McpCatalogEntry.status == STATUS_PUBLISHED)
    return query.order_by(McpCatalogEntry.title).all()


@router.get(
    "/v1alpha1/mcp/catalog/{id}", response_model=McpCatalogReviewSchema
)
def get_catalog_entry(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_platform_admin),
):
    return _review(db, _find(db, id))


@router.post(
    "/v1alpha1/mcp/catalog/import",
    response_model=McpCatalogReviewSchema,
    status_code=201,
)
async def import_catalog_entry(
    body: McpCatalogImportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_platform_admin),
):
    if not chat_mock_enabled() and mcp_registry.registry_url() is None:
        raise HTTPException(status_code=404, detail="Import is turned off")
    entry = await asyncio.to_thread(_fetch, body.name, body.version)
    if entry.deployable is None:
        raise HTTPException(
            status_code=422,
            detail="This entry cannot be deployed: "
            + (entry.deployable_reason or "it has no container image"),
        )
    slug = body.slug or mcp_registry.catalog_slug(entry.name)
    if not valid_name(slug):
        raise HTTPException(
            status_code=422,
            detail="The catalog name must be lower case letters, digits "
            "and _, start with a letter, and be at most 32 characters",
        )
    runs = _runs_of(entry.deployable)
    if (
        db.query(McpCatalogEntry.id)
        .filter(
            McpCatalogEntry.source == mcp_registry.SOURCE,
            McpCatalogEntry.source_id == entry.name,
        )
        .first()
    ):
        raise HTTPException(
            status_code=409, detail=f"{entry.name} is imported already"
        )
    if (
        db.query(McpCatalogEntry.id)
        .filter(McpCatalogEntry.name == slug)
        .first()
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Catalog name '{slug}' is taken, choose another",
        )
    row = McpCatalogEntry(
        id=genid.uuid4(),
        name=slug,
        title=entry.title,
        description=entry.description,
        docs_url=entry.website,
        command=[],
        # The narrowest mode in which most servers still work; a
        # platform admin widens it on purpose.
        egress=EGRESS_PUBLIC,
        chart_repo=CHART_REPO,
        chart_name=CHART_NAME,
        source=mcp_registry.SOURCE,
        source_id=entry.name,
        source_version=entry.version,
        status=STATUS_DRAFT,
        notes=list(entry.deployable.notes),
        synced_at=datetime.now(),
        raw=entry.raw,
        **runs,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"{entry.name} is imported already"
        ) from None
    db.refresh(row)
    return _review(db, row)


@router.patch(
    "/v1alpha1/mcp/catalog/{id}", response_model=McpCatalogReviewSchema
)
def update_catalog_entry(
    id: uuid.UUID,
    body: McpCatalogUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_platform_admin),
):
    row = _find(db, id)
    # An explicit null is no change (and never a column's value).
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None
    }
    if "status" in changes and changes["status"] not in CATALOG_STATUSES:
        raise HTTPException(
            status_code=422,
            detail="status must be one of " + ", ".join(CATALOG_STATUSES),
        )
    if "egress" in changes and changes["egress"] not in EGRESS_MODES:
        raise HTTPException(
            status_code=422,
            detail="egress must be one of " + ", ".join(EGRESS_MODES),
        )
    if "name" in changes and changes["name"] != row.name:
        # Instances and deploy requests name the entry: only a draft moves.
        if row.status != STATUS_DRAFT:
            raise HTTPException(
                status_code=409, detail="Only a draft can change its name"
            )
        if not valid_name(changes["name"]):
            raise HTTPException(status_code=422, detail="Not a valid name")
    _checked_runs(changes)
    for key, value in changes.items():
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Catalog name '{changes.get('name')}' is taken, "
            "choose another",
        ) from None
    db.refresh(row)
    return _review(db, row)


@router.post(
    "/v1alpha1/mcp/catalog/{id}/sync", response_model=McpCatalogReviewSchema
)
async def sync_catalog_entry(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_platform_admin),
):
    row = _find(db, id)
    if row.source != mcp_registry.SOURCE:
        raise HTTPException(
            status_code=409, detail="A builtin entry has no source to sync"
        )
    entry = await asyncio.to_thread(_fetch, row.source_id, None)
    if entry.deployable is None:
        raise HTTPException(
            status_code=422,
            detail="The entry can no longer be deployed: "
            + (entry.deployable_reason or "it has no container image"),
        )
    runs = _runs_of(entry.deployable)
    moved = [k for k in _RUNS if getattr(row, k) != runs[k]]
    for key in moved:
        setattr(row, key, runs[key])
    if moved:
        # Nobody has read what would run now. Instances keep running.
        row.status = STATUS_DRAFT
        row.notes = [
            f"Sync changed: {', '.join(moved)}",
            *entry.deployable.notes,
        ]
    row.source_version = entry.version
    row.raw = entry.raw
    row.synced_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _review(db, row)


@router.delete("/v1alpha1/mcp/catalog/{id}", status_code=204)
def delete_catalog_entry(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_platform_admin),
):
    row = _find(db, id)
    used = _in_use(db, row)
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"{used} deployed server(s) use this entry; deprecate it",
        )
    db.delete(row)
    db.commit()
