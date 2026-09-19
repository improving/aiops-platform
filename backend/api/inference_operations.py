"""Day-2 operations on inference instances (spec 6.2, 6.3): logs,
events and restart through the shared api/instance_inspection.py layer,
plus stop, resume and scale.

Imports from api/inference_instance.py (the row lookup) and
api/inference_status.py (the chart lookup); nothing imports from here
except core.py, which includes the router.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from api.inference_instance import _find_instance, _record_window
from api.inference_status import _engine_chart_for
from api.instance_inspection import InstanceKind, add_inspection_routes
from auth.current_user import CurrentUser, get_current_user
from auth.policy import authorize_read, authorize_write
from controller import get_controller
from db.database import get_db
from logger import setup_logger
from models.inference_instance import DBInferenceInstanceConfigParams
from schemas.inference_instance import InferenceInstanceSchema
from utils.gateway import GatewayPolicyError
from utils.instance_settings import validate_settings
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


async def _upgrade(
    db: Session,
    db_instance,
    overrides: dict | None,
    *,
    keep_when_applied: bool = False,
):
    """helm upgrade from the row as the session holds it, awaited on the
    request loop like create and update (the controller is cheap to build
    and runs its sync Kubernetes work off the loop); 500 on failure, with
    the session rolled back so nothing the caller set stays pending.

    ``keep_when_applied`` commits instead when the failure is the
    gateway's: Helm has applied the values by then, so a rollback would
    leave the row describing pods that no longer exist, and the next
    stop or scale would silently render the old values back."""
    try:
        engine, engine_chart = _engine_chart_for(db, db_instance)
        controller = get_controller(engine.name)
        full_instance = InferenceInstanceSchema.model_validate(db_instance)
        await controller.upgrade(
            full_instance,
            engine_chart,
            overrides=overrides,
        )
    except GatewayPolicyError as e:
        # Helm succeeded and the workload is serving; the gateway refused
        # the route, so say that rather than blaming Helm.
        logger.exception(f"Failed to protect the route: {str(e)}")
        if keep_when_applied:
            # The pods restart with the new values: say so on the row.
            if db_instance.status != STATUS_STOPPED:
                mark_pending(db_instance)
            db.commit()
        else:
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
    await _upgrade(db, db_instance, {"replicaCount": 0})
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
    await _upgrade(
        db, db_instance, {"replicaCount": db_instance.replicas or 1}
    )
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
    await _upgrade(db, db_instance, {"replicaCount": body.replicas})
    _leave_stopped(db_instance)
    return _respond(db, db_instance)


class SettingsRequest(BaseModel):
    """The instance's own CLI arguments and environment variables: what
    differs from the engine defaults, which the controllers merge at
    every render. Both replace what the row holds. A flag is an argument
    with an empty value."""

    args: dict[str, str] = Field(default_factory=dict)
    env_vars: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names(self):
        validate_settings(self.args, self.env_vars)
        return self


def _refuse_unread(controller, db_instance, body: SettingsRequest):
    """Only what the engine's controller renders: anything else would
    restart the pods and change nothing."""
    engine = db_instance.engine.name
    read = controller.settings_read(db_instance.model.category)
    if not read:
        raise HTTPException(
            status_code=422,
            detail=f"The {engine} engine takes no settings from the platform",
        )
    if body.args and "args" not in read:
        raise HTTPException(
            status_code=422,
            detail=f"The {engine} engine takes no CLI arguments",
        )
    if body.env_vars and "env_vars" not in read:
        raise HTTPException(
            status_code=422,
            detail=f"The {engine} engine takes no environment variables",
        )


def _refuse_fixed(db_instance, body: SettingsRequest):
    """A default the engine marks as not editable is the platform's to
    set (the form shows its value read-only): another value is refused,
    the same value is what the form sends back untouched."""
    category = db_instance.model.category
    for kind, defaults, values in (
        ("argument", db_instance.engine.default_args, body.args),
        (
            "environment variable",
            db_instance.engine.default_config,
            body.env_vars,
        ),
    ):
        for default in defaults or []:
            if default.editable or default.chart_type != category:
                continue
            fixed = str(default.defaultValue)
            if values.get(default.name, fixed) != fixed:
                raise HTTPException(
                    status_code=422,
                    detail=f"The {kind} {default.name} is set by the platform",
                )


@router.put(
    "/v1alpha1/inferenceInstance/{id}/settings",
    response_model=InferenceInstanceSchema,
)
async def update_inference_instance_settings(
    id: uuid.UUID,
    body: SettingsRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Replace the instance's own arguments and variables and upgrade, so
    its pods restart with them. A Stopped instance stays stopped: the
    values are stored and rendered, and the next resume starts from
    them."""
    db_instance = _load_for_write(db, id, user)
    engine, _ = _engine_chart_for(db, db_instance)
    _refuse_unread(get_controller(engine.name), db_instance, body)
    _refuse_fixed(db_instance, body)
    if db_instance.config is None:
        db_instance.config = DBInferenceInstanceConfigParams()
    # A vLLM instance keeps its window on the row (see _record_window):
    # a body without max_model_len would otherwise hand the instance back
    # to the default of the day and blank the chat page's meter.
    own = {"args": dict(body.args)}
    _record_window(own, db_instance.engine, db_instance.model)
    # New dicts, not edits in place: the columns are plain JSON, and a
    # mutation of the loaded value would not be seen as a change.
    db_instance.config.args = own["args"]
    db_instance.config.env_vars = dict(body.env_vars)
    stopped = db_instance.status == STATUS_STOPPED
    await _upgrade(
        db,
        db_instance,
        {"replicaCount": 0} if stopped else None,
        keep_when_applied=True,
    )
    if not stopped:
        mark_pending(db_instance)
    return _respond(db, db_instance)
