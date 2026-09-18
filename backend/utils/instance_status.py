"""Persisted instance status (spec 6.1), shared by the three routers.

``status`` on inference_instances, vectordb_instances and notebooks is one
of Pending, Running, Failed, Stopped once the platform has set it; NULL
means the row predates this and the pods have not been looked at yet.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.interfaces import LoaderOption

from logger import setup_logger
from utils.kubernetes_utils import PodStatus

logger = setup_logger(__name__)

STATUS_PENDING = "Pending"
STATUS_RUNNING = "Running"
STATUS_FAILED = "Failed"
STATUS_STOPPED = "Stopped"

# Columns a client may never set through PUT. ``replicas`` changes only
# through POST .../scale; ``gpu_count``, ``cpu`` and ``memory`` are fixed
# at launch and rendered straight into Helm values, so a PUT must not be
# able to smuggle an out-of-range or malformed value into them.
READ_ONLY_STATUS_FIELDS = frozenset(
    {
        "status",
        "last_error",
        "last_error_at",
        "stopped_at",
        "ready",
        "launch",
        "gpu_count",
        "replicas",
        "cpu",
        "memory",
    }
)

MAX_ERROR_LENGTH = 4000


def utcnow() -> datetime:
    """Naive UTC: SQLite's DateTime drops tzinfo and Postgres stores the
    value as given, so one representation goes into both."""
    return datetime.now(UTC).replace(tzinfo=None)


def mark_failed(db, row, error: BaseException | str) -> None:
    """Keep the row, record why it failed (spec 6.1)."""
    row.status = STATUS_FAILED
    row.last_error = str(error)[:MAX_ERROR_LENGTH]
    row.last_error_at = utcnow()
    db.commit()


def mark_pending(row) -> None:
    """Clear the error bookkeeping and send the row back to Pending."""
    row.status = STATUS_PENDING
    row.last_error = None
    row.last_error_at = None


def apply_pod_status(db, row, pods: PodStatus) -> bool:
    """Derive the persisted status from what the pods report and commit
    it when it changed. Returns True when a change was written.

    A Stopped row is left alone whatever the pods say (its old pod may
    still be Ready or exiting with reason Error while it drains); only
    resume leaves Stopped. Otherwise ready wins and clears the error, a
    failure reason writes ``Failed`` with ``"<reason>: <message>"`` once
    per distinct text, Failed is kept while the pods say nothing new, and
    NULL becomes Pending. ``row.launch`` is what the pods are waiting for,
    and None on a Stopped or Failed row.
    """
    status, error, error_at = row.status, row.last_error, row.last_error_at
    # Not a column: what a not-ready instance waits for, for the response
    # schema. Set on every path, so a row never carries a stale value.
    row.launch = None
    if row.status == STATUS_STOPPED:
        return False
    if pods.ready:
        status, error, error_at = STATUS_RUNNING, None, None
    elif pods.failure is not None:
        reason, message = pods.failure
        status = STATUS_FAILED
        text = f"{reason}: {message}"[:MAX_ERROR_LENGTH]
        if text != error:
            error, error_at = text, utcnow()
    elif row.status is None:
        status = STATUS_PENDING
    changed = (status, error, error_at) != (
        row.status,
        row.last_error,
        row.last_error_at,
    )
    if changed:
        row.status, row.last_error, row.last_error_at = status, error, error_at
        db.commit()
    # A failed row has last_error and the error banner; "Restarting" next
    # to them (a crash loop runs between crashes) would say less.
    if status != STATUS_FAILED:
        row.launch = pods.launch
    return changed


def stale_status_clause(model):
    """Rows the pollers refresh: ``status IS NULL OR status NOT IN
    (Running, Stopped)``. A Stopped row only ever leaves that status
    through resume, so it is excluded rather than polled every tick just
    to confirm apply_pod_status leaves it alone."""
    return or_(
        model.status.is_(None),
        model.status.notin_([STATUS_RUNNING, STATUS_STOPPED]),
    )


def refresh_stale(
    db: Session,
    model,
    check: Callable[[Any, Session, Any], Any],
    make_controller: Callable[[], Any],
    *,
    options: Sequence[LoaderOption] | None = None,
) -> int:
    """Refresh every row that is not Running or Stopped (spec 6.1); the
    scheduler jobs call this every 5 s.

    ``make_controller()`` runs once per tick, and only when there are
    rows: a controller loads the kubeconfig and runs `helm version`.
    ``check(row, db, controller)`` runs per row; a failure is logged and
    the other rows are still refreshed. ``options`` are extra SQLAlchemy
    loader options (e.g. ``joinedload(Model.relationship)``) applied to
    the stale-row query, for a ``check`` that reads a relationship --
    without it, every row issues its own lazy-load SELECT. Returns the
    number of rows seen.
    """
    query = db.query(model).filter(stale_status_clause(model))
    if options:
        query = query.options(*options)
    stale = query.all()
    if not stale:
        return 0
    controller = make_controller()
    for row in stale:
        try:
            check(row, db, controller)
        except Exception:
            logger.exception("Failed to refresh the status of %s", row.id)
    return len(stale)
