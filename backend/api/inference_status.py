"""Persisted status and endpoints of inference instances (spec 6.1).

The leaf of the inference modules: api/inference_instance.py and
api/inference_operations.py import from here, never the reverse. Holds
the engine-chart lookups, the pod status refresh and the scheduler job
core.py runs every 5 s. Tests monkeypatch ``get_controller``,
``get_pod_status_and_readiness`` and ``get_service_endpoint`` here.
"""

import uuid

from fastapi import HTTPException
from kubernetes import client
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from controller import get_controller
from logger import setup_logger
from models.engine_charts import DBEngineCharts
from models.engines import DBEngine
from models.inference_instance import DBInferenceInstance
from utils.gateway import gateway_settings, instance_url
from utils.instance_status import apply_pod_status, refresh_stale
from utils.kubernetes_utils import (
    get_pod_status_and_readiness,
    get_service_endpoint,
)

logger = setup_logger(__name__)


def missing_endpoint_clause():
    """Filter for instances whose endpoint is NULL or empty."""
    return or_(
        DBInferenceInstance.endpoint.is_(None),
        DBInferenceInstance.endpoint == "",
    )


def update_all_inference_instance_endpoints(db: Session):
    """Fill missing endpoints, then refresh the status of every instance
    that is not Running (spec 6.1); both every 5 s from core.py."""
    logger.debug("Updating all inference instance endpoints")
    try:
        instances = (
            db.query(DBInferenceInstance)
            .filter(missing_endpoint_clause())
            .all()
        )
        logger.debug(
            f"Found {len(instances)} inferenceinstances without populated endpoints"
        )
        for instance in instances:
            update_instance_endpoints(instance.id, db)

        _refresh_stale_statuses(db)
    finally:
        db.close()


def update_instance_endpoints(instanceId: uuid.UUID, db: Session):
    """
    Update the endpoints for an inference instance.

    Args:
        instanceId (uuid.UUID): The ID of the inference instance to update.
        db (Session): The database session.
    """
    logger.info(f"Updating endpoints for instance {instanceId}")
    instance = (
        db.query(DBInferenceInstance)
        .options(
            joinedload(DBInferenceInstance.model),
            joinedload(DBInferenceInstance.engine),
        )
        .filter(DBInferenceInstance.id == instanceId)
        .first()
    )
    engine, engine_chart = _engine_chart_for(db, instance)
    controller = get_controller(engine.name)
    service_name = controller.get_service_name(instance, engine_chart)

    if gateway_settings() is not None:
        # The hostname is deterministic, so the endpoint is set as soon as
        # the gateway is configured, without waiting for the Service.
        # No trailing slash: the UI and SDK clients append paths such as
        # /v1/chat/completions to this value.
        instance.endpoint = instance_url("inf", instance.id, path="")
        db.commit()
        return

    try:
        endpoint = get_service_endpoint(controller.namespace, service_name)

        if endpoint:
            # Update the instance endpoint
            instance.endpoint = endpoint
            instance.healthEndpoint = f"{endpoint}/health"
            instance.metricsEndpoint = f"{endpoint}/metrics"

            # Update the database
            db.commit()
        else:
            logger.warning(
                f"Warning: Could not determine IP or port for service {service_name}"
            )

    except client.exceptions.ApiException as e:
        logger.exception(f"Error getting service information: {e}")
    # Don't raise an exception here, as we still want to return the instance information


def _engine_chart_query(db: Session, engine_name: str, category: str):
    """The chart row for an engine and a model category, or None: the
    engine_charts table keys on the engine's name and the chart type."""
    return (
        db.query(DBEngineCharts)
        .filter(
            and_(
                DBEngineCharts.engine == engine_name,
                DBEngineCharts.chart_type == category,
            )
        )
        .first()
    )


def _engine_chart_for(db: Session, instance: DBInferenceInstance):
    """The engine row and its chart row for the instance; 404 when gone."""
    engine = (
        db.query(DBEngine).filter(DBEngine.id == instance.engine_id).first()
    )
    if not engine:
        raise HTTPException(
            status_code=404, detail="Associated engine not found"
        )
    engine_chart = _engine_chart_query(
        db, engine.name, instance.model.category
    )
    if not engine_chart:
        raise HTTPException(
            status_code=404, detail="Associated engine chart not found"
        )
    return engine, engine_chart


def _refresh_status(db: Session, instance, controller, engine_chart):
    """Look at the pods through a controller the caller already built,
    persist the derived status (utils/instance_status), return the pods."""
    pods = get_pod_status_and_readiness(
        controller.namespace,
        controller.get_pod_labels(instance, engine_chart),
    )
    apply_pod_status(db, instance, pods)
    return pods


def check_pod_status_and_readiness(
    instance: DBInferenceInstance, db: Session, controller=None
):
    """(ready, persisted status) for one instance; the controller is
    built for the row's engine unless the caller passes one.

    A row whose engine or chart row is gone (a launch that failed before
    the chart existed and was kept as ``Failed``) cannot be refreshed;
    it keeps its persisted status and reads as not ready, so a list or
    detail request never fails because of one such row.
    """
    try:
        engine, engine_chart = _engine_chart_for(db, instance)
    except HTTPException as e:
        logger.debug(
            f"instance {instance.id}: status not refreshed: {e.detail}"
        )
        return False, instance.status
    controller = controller or get_controller(engine.name)
    pods = _refresh_status(db, instance, controller, engine_chart)
    return pods.ready, instance.status


# In the per-tick controller cache: this engine's controller could not be
# built, so its other rows are skipped without a second warning.
_UNAVAILABLE = object()


def _refresh_stale_status(instance, db: Session, controllers: dict) -> None:
    """One row of the poller: ``controllers`` is the tick's per-engine
    cache (refresh_stale builds one ``dict`` per tick), since
    ``ensure_ready()`` loads the kubeconfig once per engine, not once
    per row.

    A row whose engine or chart row is gone (an install that failed
    before the chart existed) is skipped with one debug line, not a
    traceback every 5 s; an engine whose controller fails to build
    (unreachable cluster, bad kubeconfig) is skipped with one warning
    line for the whole tick, not a traceback per row.
    """
    try:
        engine, engine_chart = _engine_chart_for(db, instance)
    except HTTPException as e:
        logger.debug("Skipping the status of %s: %s", instance.id, e.detail)
        return
    controller = controllers.get(engine.name)
    if controller is None:
        try:
            controller = get_controller(engine.name)
            # Construction is lazy (Controller's docstring), so without
            # this a missing kubeconfig or an unreachable cluster only
            # surfaces later, inside _refresh_status, as one traceback
            # per stale row instead of one warning for the whole tick.
            controller.ensure_ready()
            controllers[engine.name] = controller
        except Exception as exc:
            controllers[engine.name] = _UNAVAILABLE
            logger.warning(
                "Skipping the %s status refresh this tick: %s",
                engine.name,
                exc,
            )
            return
    if controller is _UNAVAILABLE:
        return
    _refresh_status(db, instance, controller, engine_chart)


def _refresh_stale_statuses(db: Session) -> None:
    """Refresh every instance that is not Running or Stopped (spec 6.1).

    ``_engine_chart_for`` reads ``instance.model.category``, so the
    ``model`` relationship is joined up front -- otherwise every stale
    row issues its own lazy-load SELECT every 5 s.
    """
    refresh_stale(
        db,
        DBInferenceInstance,
        _refresh_stale_status,
        dict,
        options=[joinedload(DBInferenceInstance.model)],
    )
