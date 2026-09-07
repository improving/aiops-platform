"""``GET /v1alpha1/organizations/current/audit``: the organization's audit
trail, newest first, keyset-paged by (at, id), as JSON or CSV (spec 5.3)."""

import base64
import csv
import io
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from auth.current_user import NOT_PLATFORM_ADMIN, CurrentUser, require_admin
from db.database import get_db
from models.audit_event import AuditEvent

router = APIRouter()

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
# The CSV export ignores `limit` and pages through every matching row
# itself, so a very large export does not hold them all in memory at once.
CSV_PAGE_SIZE = 1000
# A hard ceiling so a runaway export cannot stream forever.
CSV_ROW_CAP = 100_000
CSV_COLUMNS = (
    "at",
    "actor",
    "action",
    "resource_kind",
    "resource_id",
    "outcome",
    "request_id",
)
NAIVE_TIMESTAMPS_ONLY = "from and to must be naive ISO 8601 timestamps"
# Cells that would open as a formula in a spreadsheet: escape a leading
# one of these with a single quote (actor, resource_kind and request_id
# are attacker-influenced).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def encode_cursor(at: datetime, event_id: uuid.UUID) -> str:
    raw = f"{at.isoformat()}|{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at_text, id_text = (
            base64.urlsafe_b64decode(padded).decode().split("|", 1)
        )
        at = datetime.fromisoformat(at_text)
        if at.tzinfo is not None:
            raise HTTPException(status_code=422, detail=NAIVE_TIMESTAMPS_ONLY)
        return at, uuid.UUID(id_text)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor")


def _event_document(event: AuditEvent) -> dict:
    return {
        "id": str(event.id),
        "at": event.at,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_label": event.actor_label,
        "action": event.action,
        "resource_kind": event.resource_kind,
        "resource_id": event.resource_id,
        "outcome": event.outcome,
        "request_id": event.request_id,
        "detail": event.detail,
    }


def _query(
    db: Session,
    org_id,
    since: datetime | None,
    until: datetime | None,
    actor: str | None,
    action: str | None,
    resource_kind: str | None,
    cursor: str | None,
    include_anonymous: bool = False,
):
    if include_anonymous:
        query = db.query(AuditEvent).filter(
            or_(AuditEvent.org_id == org_id, AuditEvent.org_id.is_(None))
        )
    else:
        query = db.query(AuditEvent).filter(AuditEvent.org_id == org_id)
    if since is not None:
        query = query.filter(AuditEvent.at >= since)
    if until is not None:
        query = query.filter(AuditEvent.at <= until)
    if actor:
        query = query.filter(
            AuditEvent.actor_label.contains(actor, autoescape=True)
        )
    if action:
        query = query.filter(AuditEvent.action == action)
    if resource_kind:
        query = query.filter(AuditEvent.resource_kind == resource_kind)
    if cursor:
        at, event_id = decode_cursor(cursor)
        query = query.filter(
            or_(
                AuditEvent.at < at,
                and_(AuditEvent.at == at, AuditEvent.id < event_id),
            )
        )
    return query.order_by(AuditEvent.at.desc(), AuditEvent.id.desc())


def _csv_safe(value: str) -> str:
    """Escape a cell that a spreadsheet would open as a formula."""
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_row(event: AuditEvent) -> list:
    return [
        event.at.isoformat(),
        _csv_safe(event.actor_label),
        _csv_safe(event.action),
        _csv_safe(event.resource_kind),
        _csv_safe(event.resource_id or ""),
        event.outcome,
        _csv_safe(event.request_id or ""),
    ]


def _csv_stream(
    db: Session,
    org_id,
    since: datetime | None,
    until: datetime | None,
    actor: str | None,
    action: str | None,
    resource_kind: str | None,
    include_anonymous: bool,
) -> Iterator[str]:
    """Every matching row, newest first, paged through the same cursor the
    JSON list uses so a large export never holds every row in memory at
    once; a hard cap stops a runaway export."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    yield buffer.getvalue()
    emitted = 0
    cursor: str | None = None
    truncated = False
    while True:
        page = (
            _query(
                db,
                org_id,
                since,
                until,
                actor,
                action,
                resource_kind,
                cursor,
                include_anonymous,
            )
            .limit(CSV_PAGE_SIZE)
            .all()
        )
        if not page:
            break
        for event in page:
            if emitted >= CSV_ROW_CAP:
                truncated = True
                break
            buffer.seek(0)
            buffer.truncate()
            writer.writerow(_csv_row(event))
            yield buffer.getvalue()
            emitted += 1
        if truncated or len(page) < CSV_PAGE_SIZE:
            break
        last = page[-1]
        cursor = encode_cursor(last.at, last.id)
    if truncated:
        yield "# truncated\n"


@router.get("/v1alpha1/organizations/current/audit")
def list_audit_events(
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    actor: str | None = None,
    action: str | None = None,
    resource_kind: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    format: Literal["json", "csv"] = "json",
    include_anonymous: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    if (since is not None and since.tzinfo is not None) or (
        until is not None and until.tzinfo is not None
    ):
        raise HTTPException(status_code=422, detail=NAIVE_TIMESTAMPS_ONLY)
    if include_anonymous and not user.is_platform_admin:
        raise HTTPException(status_code=403, detail=NOT_PLATFORM_ADMIN)
    if format == "csv":
        return StreamingResponse(
            _csv_stream(
                db,
                user.org_id,
                since,
                until,
                actor,
                action,
                resource_kind,
                include_anonymous,
            ),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="audit.csv"'
            },
        )
    query = _query(
        db,
        user.org_id,
        since,
        until,
        actor,
        action,
        resource_kind,
        cursor,
        include_anonymous,
    )
    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1].at, rows[-1].id) if has_more and rows else None
    )
    return {
        "events": [_event_document(e) for e in rows],
        "next_cursor": next_cursor,
    }
