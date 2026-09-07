"""Day-2 operations on inference instances (spec 6.2, 6.3): logs,
events and restart through the shared api/instance_inspection.py layer,
plus stop, resume and scale.

Imports from api/inference_instance.py (the row lookup) and
api/inference_status.py (the chart lookup); nothing imports from here
except core.py, which includes the router.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.inference_instance import _find_instance
from api.inference_status import _engine_chart_for
from api.instance_inspection import InstanceKind, add_inspection_routes
from auth.current_user import CurrentUser, get_current_user
from auth.policy import authorize_read, authorize_write
from controller import get_controller
from db.database import get_db
from logger import setup_logger
from schemas.inference_instance import InferenceInstanceSchema
from utils.gateway import GatewayPolicyError
from utils.instance_status import (
    STATUS_STOPPED,
    mark_pending,
    utcnow,
)

router = APIRouter()
logger = setup_logger(__name__)


INFERENCE_KIND = InstanceKind(
    label="inference instance",
    find=_find_instance,
    authorize_read=authorize_read,
    authorize_write=authorize_write,
    make_controller=lambda db, row: get_controller(
        _engine_chart_for(db, row)[0].name
    ),
    namespace=lambda controller, row: controller.namespace,
    pod_labels=lambda db, controller, row: controller.get_pod_labels(
        row, _engine_chart_for(db, row)[1]
    ),
    restart=True,
    response_model=InferenceInstanceSchema,
)
add_inspection_routes(router, "/v1alpha1/inferenceInstance", INFERENCE_KIND)


class ScaleRequest(BaseModel):
    replicas: int = Field(ge=0, le=16)


def _load_for_write(db: Session, id: uuid.UUID, user: CurrentUser):
    db_instance = _find_instance(db, id, user)
    authorize_write(user, db_instance, "inference instance")
    return db_instance


async def _set_replica_count(db: Session, db_instance, replica_count: int):
    """helm upgrade with replicaCount overridden, awaited on the request
    loop like create and update (the controller is cheap to build and
    runs its sync Kubernetes work off the loop); 500 on failure."""
    try:
        engine, engine_chart = _engine_chart_for(db, db_instance)
        controller = get_controller(engine.name)
        full_instance = InferenceInstanceSchema.model_validate(db_instance)
        await controller.upgrade(
            full_instance,
            engine_chart,
            overrides={"replicaCount": replica_count},
        )
    except GatewayPolicyError as e:
        # Helm succeeded and the workload is serving; the gateway refused
        # the route, so say that rather than blaming Helm.
        logger.exception(f"Failed to protect the route: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to protect the gateway route: {str(e)}",
        )
    except Exception as e:
        logger.exception(f"Failed to upgrade Helm chart: {str(e)}")
        # scale sets `replicas` on the row before calling this; a failed
        # upgrade must not leave that value pending in the session.
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upgrade Helm chart: {str(e)}",
        )


def _respond(db: Session, db_instance):
    db.commit()
    db.refresh(db_instance)
    db_instance.ready = False
    return db_instance


def _leave_stopped(db_instance):
    """Clear the bookkeeping stop leaves behind (spec 6.3): resume and a
    scale back up from Stopped share this exactly, so an old error never
    survives either one."""
    mark_pending(db_instance)
    db_instance.stopped_at = None


async def _stop(db: Session, db_instance):
    """A Stopped row is left alone: helm upgrade already ran and
    ``stopped_at`` already marks when, so stopping it again is a no-op."""
    if db_instance.status == STATUS_STOPPED:
        return _respond(db, db_instance)
    await _set_replica_count(db, db_instance, 0)
    db_instance.status = STATUS_STOPPED
    db_instance.stopped_at = utcnow()
    return _respond(db, db_instance)


@router.post(
    "/v1alpha1/inferenceInstance/{id}/stop",
    response_model=InferenceInstanceSchema,
)
async def stop_inference_instance(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """replicaCount 0; the row, its credential and its LiteLLM
    registration are kept, so resume is a plain upgrade."""
    db_instance = _load_for_write(db, id, user)
    return await _stop(db, db_instance)


@router.post(
    "/v1alpha1/inferenceInstance/{id}/resume",
    response_model=InferenceInstanceSchema,
)
async def resume_inference_instance(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    db_instance = _load_for_write(db, id, user)
    await _set_replica_count(db, db_instance, db_instance.replicas or 1)
    _leave_stopped(db_instance)
    return _respond(db, db_instance)


@router.post(
    "/v1alpha1/inferenceInstance/{id}/scale",
    response_model=InferenceInstanceSchema,
)
async def scale_inference_instance(
    id: uuid.UUID,
    body: ScaleRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Store the replica count and upgrade; 0 is a stop and keeps the
    stored count for the next resume."""
    db_instance = _load_for_write(db, id, user)
    if body.replicas == 0:
        return await _stop(db, db_instance)
    db_instance.replicas = body.replicas
    await _set_replica_count(db, db_instance, body.replicas)
    _leave_stopped(db_instance)
    return _respond(db, db_instance)
