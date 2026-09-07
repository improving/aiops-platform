"""The HTTP layer the three instance routers share (spec 6.2, 6.3):
logs, events and restart for one instance kind.

Each router describes its kind once (``InstanceKind``) and registers the
routes with ``add_inspection_routes``; the paths, query parameters,
response shapes, status codes and ``detail`` strings are the ones the
routers used to define by hand, so the UI and the tests see no change.

The callables in ``InstanceKind`` are defined in the router modules and
look their collaborators up at call time, so a test that monkeypatches
``api.notebooks.NotebooksController`` or ``api.inference_status.get_controller``
still reaches this module; ``restart_workload`` is looked up here.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.current_user import CurrentUser, get_current_user
from db.database import get_db
from logger import setup_logger
from utils.instance_status import STATUS_STOPPED, mark_pending
from utils.kubernetes_utils import restart_workload
from utils.pod_inspection import MAX_TAIL, pod_events, pod_logs

logger = setup_logger(__name__)

# The auth.policy signature: (user, row, label) -> None or 403.
Authorizer = Callable[[CurrentUser, Any, str], None]


@dataclass(frozen=True)
class InstanceKind:
    """What the shared routes need to know about one instance kind."""

    # "inference instance", "vector database instance", "notebook": the
    # label auth.policy puts in its 403 messages.
    label: str
    # Query-or-404 with the caller's scope applied.
    find: Callable[[Session, uuid.UUID, CurrentUser], Any]
    # Notebooks keep authorize_owner, the other two authorize_read.
    authorize_read: Authorizer
    authorize_write: Authorizer
    # One controller for this row (inference: by engine).
    make_controller: Callable[[Session, Any], Any]
    # (controller, row) -> the namespace the pods live in: notebooks
    # carry it on the row, the other two take the controller's.
    namespace: Callable[[Any, Any], str]
    # (db, controller, row) -> the pod label selector.
    pod_labels: Callable[[Session, Any, Any], str]
    # Register POST {prefix}/{id}/restart.
    restart: bool
    # The response model of the restart route (the row's schema).
    response_model: type | None = None


def _pods(kind: InstanceKind, db: Session, row) -> tuple[str, str]:
    """(namespace, label selector); runs off the event loop because
    constructing a controller loads the kube config (blocking file I/O)
    and may run `helm version`."""
    controller = kind.make_controller(db, row)
    return kind.namespace(controller, row), kind.pod_labels(
        db, controller, row
    )


def _read_logs_sync(kind, db, row, tail, previous, container):
    namespace, labels = _pods(kind, db, row)
    return pod_logs(namespace, labels, tail, previous, container)


def _read_events_sync(kind, db, row):
    namespace, labels = _pods(kind, db, row)
    return pod_events(namespace, labels)


def _restart_sync(kind, db, row):
    namespace, labels = _pods(kind, db, row)
    return restart_workload(namespace, labels)


def add_inspection_routes(
    router: APIRouter, prefix: str, kind: InstanceKind
) -> None:
    """Registers GET {prefix}/{id}/logs, GET {prefix}/{id}/events and,
    when kind.restart, POST {prefix}/{id}/restart.

    The route names carry the kind so the OpenAPI operation ids stay
    unique across the three routers.
    """
    slug = kind.label.replace(" ", "_")

    async def get_logs(
        id: uuid.UUID,
        container: str | None = None,
        tail: int = Query(200, ge=1, le=MAX_TAIL),
        previous: bool = False,
        db: Session = Depends(get_db),
        user: CurrentUser = Depends(get_current_user),
    ):
        """The logs of the instance's pods (spec 6.2)."""
        row = kind.find(db, id, user)
        kind.authorize_read(user, row, kind.label)
        try:
            return await asyncio.to_thread(
                _read_logs_sync, kind, db, row, tail, previous, container
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Failed to read the logs of {id}: {e}")
            raise HTTPException(
                status_code=502, detail=f"Could not read the logs: {e}"
            )

    async def get_events(
        id: uuid.UUID,
        db: Session = Depends(get_db),
        user: CurrentUser = Depends(get_current_user),
    ):
        """The Kubernetes events of the instance's pods and workload."""
        row = kind.find(db, id, user)
        kind.authorize_read(user, row, kind.label)
        try:
            return await asyncio.to_thread(_read_events_sync, kind, db, row)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Failed to read the events of {id}: {e}")
            raise HTTPException(
                status_code=502, detail=f"Could not read the events: {e}"
            )

    async def restart(
        id: uuid.UUID,
        db: Session = Depends(get_db),
        user: CurrentUser = Depends(get_current_user),
    ):
        """Roll the pods (kubectl rollout restart); status back to Pending."""
        row = kind.find(db, id, user)
        kind.authorize_write(user, row, kind.label)
        if row.status == STATUS_STOPPED:
            raise HTTPException(
                status_code=409,
                detail="The instance is stopped; resume it first",
            )
        try:
            await asyncio.to_thread(_restart_sync, kind, db, row)
        except LookupError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Failed to restart {id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to restart: {e}"
            )
        mark_pending(row)
        db.commit()
        db.refresh(row)
        row.ready = False
        return row

    router.add_api_route(
        f"{prefix}/{{id}}/logs",
        get_logs,
        methods=["GET"],
        name=f"get_{slug}_logs",
    )
    router.add_api_route(
        f"{prefix}/{{id}}/events",
        get_events,
        methods=["GET"],
        name=f"get_{slug}_events",
    )
    if kind.restart:
        router.add_api_route(
            f"{prefix}/{{id}}/restart",
            restart,
            methods=["POST"],
            name=f"restart_{slug}",
            response_model=kind.response_model,
        )
