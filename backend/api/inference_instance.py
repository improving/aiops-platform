import json
import os
import pprint
import uuid
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException
from kubernetes import client
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from db.database import SessionLocal, get_db
from logger import setup_logger
from models.engine_chart_dashboards import DBEngineChartDashboards
from models.engine_charts import DBEngineCharts
from models.engines import DBEngine
from models.inference_instance import (DBInferenceInstance,
                                       DBInferenceInstanceConfigParams)
from models.inference_instance_dashboards import DBInferenceInstanceDashboards
from models.model_adapters import DBModelAdapters
from models.models import DBModel
from schemas.inference_instance import InferenceInstanceSchema
from schemas.inference_instance_dashboards import \
    InferenceInstanceDashboardsSchema
from utils.controller_utils import get_controller
from utils.kubernetes_utils import (get_pod_status_and_readiness,
                                    get_service_endpoint)

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)

# Static org_id for all dashboards
org_id = "1"


@router.get("/v1alpha1/inferenceInstance",
            response_model=List[InferenceInstanceSchema])
async def list_inference_instances(db: Session = Depends(get_db)):
    """
    List all inference instances.

    Args:
        db (Session): The database session, injected by FastAPI.

    Returns:
        List[InferenceInstanceSchema]: A list of all inference instances.

    Raises:
        HTTPException: If there's an error retrieving the inference instances.
    """
    try:
        instances = db.query(DBInferenceInstance).all()
        for instance in instances:
            instance_ready, instance_status = check_pod_status_and_readiness(
                instance, db)
            instance.ready = instance_ready
            instance.status = instance_status
        return instances
    except Exception as e:
        logger.exception(f"Error in list_inference_instances: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/v1alpha1/inferenceInstance/{id}",
            response_model=InferenceInstanceSchema)
async def get_inference_instance(id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Retrieve a specific inference instance by ID.

    Args:
        id (uuid.UUID): The ID of the inference instance to retrieve.

    Returns:
        InferenceInstanceSchema: The requested inference instance.

    Raises:
        HTTPException: If the inference instance is not found or there's an internal error.
    """
    try:
        instance = db.query(DBInferenceInstance).filter(
            DBInferenceInstance.id == id).first()
        if not instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(status_code=404,
                                detail="Inference instance not found")

        instance.ready, instance.status = check_pod_status_and_readiness(
            instance, db)

        return instance
    except HTTPException:
        logger.exception("HTTPException in get_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in get_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/v1alpha1/inferenceInstance/{id}/dashboards",
            response_model=List[InferenceInstanceDashboardsSchema])
async def get_inference_instance_dashboards(id: uuid.UUID,
                                            db: Session = Depends(get_db)):
    """
    Retrieve dashboards for a specific inference instance.

    Args:
        id (uuid.UUID): The ID of the inference instance.

    Returns:
        List[InferenceInstanceDashboardsSchema]: A list of dashboards associated with the inference instance.

    Raises:
        HTTPException: If there's an error retrieving the dashboards.
    """
    try:
        db_instance_dashboards = db.query(
            DBInferenceInstanceDashboards).filter(
                DBInferenceInstanceDashboards.inference_instance_id ==
                id).all()

        if not db_instance_dashboards:
            return []

        instance_dashboard_list = []
        for db_instance_dashboard in db_instance_dashboards:
            instance_dashboard = InferenceInstanceDashboardsSchema(
                id=db_instance_dashboard.id,
                org_id=db_instance_dashboard.org_id,
                query_params=json.loads(db_instance_dashboard.query_params))
            chart_dashboard = db.query(DBEngineChartDashboards).filter(
                DBEngineChartDashboards.id ==
                db_instance_dashboard.engine_chart_dashboard_id).first()
            if chart_dashboard:
                instance_dashboard.dashboard_id = chart_dashboard.dashboard_id
                instance_dashboard.dashboard_name = chart_dashboard.dashboard_name
                instance_dashboard.panel_id = chart_dashboard.panel_id
                instance_dashboard.panel_name = chart_dashboard.panel_name
            instance_dashboard_list.append(instance_dashboard)

        return instance_dashboard_list
    except Exception as e:
        logger.exception(
            f"Error in get_inference_instance_dashboards: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/v1alpha1/inferenceInstance",
             response_model=InferenceInstanceSchema,
             status_code=201)
async def create_inference_instance(instance: InferenceInstanceSchema,
                                    db: Session = Depends(get_db)):
    """
    Create a new inference instance.

    Args:
        instance (InferenceInstanceSchema): The inference instance data.

    Returns:
        InferenceInstanceSchema: The created inference instance.

    Raises:
        HTTPException: If there's an error creating the inference instance.
    """
    try:
        model = db.query(DBModel).filter(
            DBModel.id == instance.model.id).first()
        engine = db.query(DBEngine).filter(
            DBEngine.id == instance.engine.id).first()

        if not model or not engine:
            logger.error(
                f"Model or Engine not found: model_id={instance.model.id}, engine_id={instance.engine.id}"
            )
            raise HTTPException(status_code=404,
                                detail="Model or Engine not found")

        engine_chart = db.query(DBEngineCharts).filter(
            and_(DBEngineCharts.engine == engine.name,
                 DBEngineCharts.chart_type == model.category)).first()
        if not engine_chart:
            logger.error(
                f"Model Engine combination is invalid: model: {model.name}, engine: {engine.name}"
            )

        HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
        NGC_API_KEY = os.environ.get("NGC_API_KEY")

        if engine.name == 'nim' and not NGC_API_KEY:
            logger.error("NGC API key not set")
            raise HTTPException(status_code=400, detail="NGC API key not set")
        if not HF_API_TOKEN:
            logger.error("HuggingFace API token not set")
            raise HTTPException(status_code=400,
                                detail="HuggingFace API token not set.")

        config_data = instance.config.model_dump() if instance.config else {}

        # Handle lora_adapters separately
        lora_adapters = update_config_with_lora_adapters(
            db, config_data.pop('lora_adapters', []))
        db_config = DBInferenceInstanceConfigParams(**config_data)
        db_config.lora_adapters = lora_adapters

        db_instance = DBInferenceInstance(
            model_id=instance.model.id,
            engine_id=instance.engine.id,
            host=instance.host,
            endpoint=instance.endpoint or "",
            healthEndpoint=instance.healthEndpoint or "",
            metricsEndpoint=instance.metricsEndpoint or "",
            config=db_config)

        db.add(db_config)
        db.add(db_instance)
        db.commit()
        db.refresh(db_instance)

        full_instance = InferenceInstanceSchema.model_validate(db_instance)

        logger.debug(
            f"Full instance:\n{pprint.pformat(full_instance.model_dump(), indent=4, width=120)}"
        )

        controller = get_controller(engine.name)

        try:
            await controller.install(full_instance, engine_chart)
        except Exception as e:
            db.delete(db_instance)
            db.delete(db_config)
            db.commit()
            logger.exception(f"Failed to install Helm chart: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to install Helm chart: {str(e)}")

        await create_instance_dashboards(full_instance, engine_chart, db)

        return full_instance
    except HTTPException:
        logger.exception("HTTPException in create_inference_instance")
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error in create_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


def update_config_with_lora_adapters(db, lora_adapters):
    """
    Update the configuration with LoRA adapters.

    Args:
        lora_adapters (list): A list of LoRA adapter configurations.

    Returns:
        list: A list of DBModelAdapters objects.

    Raises:
        HTTPException: If a model adapter is not found.
    """
    lora_adapters_list = []
    for adapter in lora_adapters:
        existing_adapter = db.query(DBModelAdapters).filter(
            DBModelAdapters.id == adapter['id']).first()
        if existing_adapter:
            lora_adapters_list.append(existing_adapter)
        else:
            logger.error(f"Model adapter with id {adapter['id']} not found")
            raise HTTPException(status_code=404,
                                detail="Model adapter not found")
    return lora_adapters_list


@router.put("/v1alpha1/inferenceInstance/{id}",
            response_model=InferenceInstanceSchema)
async def update_inference_instance(id: uuid.UUID,
                                    updated_instance: InferenceInstanceSchema,
                                    db: Session = Depends(get_db)):
    """
    Update an existing inference instance.

    Args:
        id (uuid.UUID): The ID of the inference instance to update.
        updated_instance (InferenceInstanceSchema): The updated inference instance data.

    Returns:
        InferenceInstanceSchema: The updated inference instance.

    Raises:
        HTTPException: If the inference instance is not found or there's an error during the update.
    """
    try:
        db_instance = db.query(DBInferenceInstance).filter(
            DBInferenceInstance.id == id).first()
        if not db_instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(status_code=404,
                                detail="Inference instance not found")

        for key, value in updated_instance.model_dump(
                exclude_unset=True).items():
            if key == 'config':
                update_config_params(db, db_instance, value)
            else:
                setattr(db_instance, key, value)

        model = db.query(DBModel).filter(
            DBModel.id == db_instance.model_id).first()
        engine = db.query(DBEngine).filter(
            DBEngine.id == db_instance.engine_id).first()
        engine_chart = db.query(DBEngineCharts).filter(
            and_(DBEngineCharts.engine == engine.name,
                 DBEngineCharts.chart_type == model.category)).first()

        full_instance = InferenceInstanceSchema.model_validate(db_instance)

        controller = get_controller(engine.name)

        try:
            await controller.upgrade(full_instance, engine_chart)
        except Exception as e:
            logger.exception(f"Failed to upgrade Helm chart: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upgrade Helm chart: {str(e)}")

        db.commit()
        db.refresh(db_instance)
        return db_instance
    except HTTPException:
        logger.exception("HTTPException in update_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in update_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


def update_config_params(db, db_instance, value):
    """
    Update the configuration parameters of an inference instance.

    Args:
        db_instance (DBInferenceInstance): The inference instance to update.
        value (dict): The new configuration values.
    """
    for config_key, config_value in value.items():
        if config_key == 'lora_adapters':
            update_lora_adapters_in_inference_instance_config(
                db, db_instance, config_key, config_value)
        else:
            setattr(db_instance.config, config_key, config_value)


def update_lora_adapters_in_inference_instance_config(db, db_instance,
                                                      config_key,
                                                      config_value):
    """
    Update the LoRA adapters in the inference instance configuration.

    Args:
        db_instance (DBInferenceInstance): The inference instance to update.
        config_key (str): The configuration key for LoRA adapters.
        config_value (list): The new LoRA adapter configurations.

    Raises:
        HTTPException: If a model adapter is not found.
    """
    for adapter in config_value:
        existing_adapter = db.query(DBModelAdapters).filter(
            DBModelAdapters.id == adapter['id']).first()
        if existing_adapter:
            setattr(db_instance.config, config_key, config_value)
        else:
            logger.error(f"Model adapter with id {adapter['id']} not found")
            raise HTTPException(status_code=404,
                                detail="Model adapter not found")


@router.delete("/v1alpha1/inferenceInstance/{id}")
async def delete_inference_instance(id: uuid.UUID,
                                    db: Session = Depends(get_db)):
    """
    Delete an inference instance.

    Args:
        id (uuid.UUID): The ID of the inference instance to delete.

    Returns:
        dict: A message confirming the deletion.

    Raises:
        HTTPException: If the inference instance is not found or there's an error during deletion.
    """
    try:
        db_instance = db.query(DBInferenceInstance).filter(
            DBInferenceInstance.id == id).first()
        if not db_instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(status_code=404,
                                detail="Inference instance not found")

        full_instance = InferenceInstanceSchema.model_validate(db_instance)
        controller = get_controller(full_instance.engine.name)

        try:
            await controller.uninstall(full_instance)
        except Exception as e:
            logger.exception(f"Failed to remove Helm chart: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove Helm chart: {str(e)}")

        try:
            instance_dashboards = db.query(
                DBInferenceInstanceDashboards).filter(
                    DBInferenceInstanceDashboards.inference_instance_id ==
                    id).all()
            if instance_dashboards:
                for dashboard in instance_dashboards:
                    db.delete(dashboard)

            db.delete(db_instance.config)
            db.delete(db_instance)
            db.commit()
        except Exception as e:
            logger.exception(f"Error deleting dashboards: {e}")

        return {"detail": "Inference instance deleted"}
    except HTTPException:
        logger.exception("HTTPException in delete_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in delete_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def create_instance_dashboards(instance: InferenceInstanceSchema,
                                     engine_chart: DBEngineCharts,
                                     db: Session):
    """
    Create dashboards for an inference instance.

    Args:
        instance (InferenceInstanceSchema): The inference instance to create dashboards for.
        engine_chart (DBEngineCharts): The engine chart to create dashboards for.
        db (Session): The database session.

    Raises:
        HTTPException: If no dashboards are found for the engine chart.
    """
    try:
        engine_chart_dashboards = db.query(DBEngineChartDashboards).filter(
            and_(DBEngineChartDashboards.engine_id == instance.engine.id,
                 DBEngineChartDashboards.engine_chart_id ==
                 engine_chart.id)).all()
        if not engine_chart_dashboards:
            logger.error(
                f"No dashboards found for engine chart: {engine_chart.id}")
            return

        for chart_dashboard in engine_chart_dashboards:
            controller = get_controller(instance.engine.name)
            namespace = controller.namespace
            service_name = controller.get_service_name(instance, engine_chart)
            query_params = {
                "var-namespace": namespace,
                "var-service": service_name,
            }
            inference_instance_dashboard = DBInferenceInstanceDashboards(
                id=uuid.uuid4(),
                inference_instance_id=instance.id,
                engine_chart_dashboard_id=chart_dashboard.id,
                org_id=org_id,
                query_params=json.dumps(query_params))
            db.add(inference_instance_dashboard)

        db.commit()
    except Exception as e:
        logger.exception(f"Error creating instance dashboards: {e}")
        raise HTTPException(status_code=500,
                            detail=f"Error creating instance dashboards: {e}")


def update_all_instance_endpoints():
    """
    Update all inference instance endpoints.
    """
    logger.debug("Updating all inference instance endpoints")
    db = SessionLocal()
    try:
        # Query for instances without populated endpoints
        instances = db.query(DBInferenceInstance).filter(
            or_(DBInferenceInstance.endpoint is None,
                DBInferenceInstance.endpoint == '')).all()

        logger.debug(
            f"Found {len(instances)} inferenceinstances without populated endpoints"
        )

        for instance in instances:
            update_instance_endpoints(instance, db)
    finally:
        db.close()


def update_instance_endpoints(instance: DBInferenceInstance, db: Session):
    """
    Update the endpoints for an inference instance.

    Args:
        instance (DBInferenceInstance): The inference instance to update.
        db (Session): The database session.
    """
    logger.info(f"Updating endpoints for instance {instance.id}")
    engine = db.query(DBEngine).filter(
        DBEngine.id == instance.engine_id).first()
    if not engine:
        raise HTTPException(status_code=404,
                            detail="Associated engine not found")

    engine_chart = db.query(DBEngineCharts).filter(
        and_(DBEngineCharts.engine == engine.name,
             DBEngineCharts.chart_type == instance.model.category)).first()
    if not engine_chart:
        raise HTTPException(status_code=404,
                            detail="Associated engine chart not found")

    controller = get_controller(engine.name)
    service_name = controller.get_service_name(instance, engine_chart)

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


def check_pod_status_and_readiness(instance: DBInferenceInstance, db: Session):
    """
    Check the status and readiness of an inference instance's pod.

    Args:
        instance (DBInferenceInstance): The inference instance to check.

    Returns:
        tuple: A tuple containing the readiness status and the pod status.

    Raises:
        HTTPException: If the associated engine or engine chart is not found.
    """
    # Get the associated engine
    engine = db.query(DBEngine).filter(
        DBEngine.id == instance.engine_id).first()
    if not engine:
        raise HTTPException(status_code=404,
                            detail="Associated engine not found")

    engine_chart = db.query(DBEngineCharts).filter(
        and_(DBEngineCharts.engine == engine.name,
             DBEngineCharts.chart_type == instance.model.category)).first()
    if not engine_chart:
        raise HTTPException(status_code=404,
                            detail="Associated engine chart not found")

    controller = get_controller(engine.name)
    pod_labels = controller.get_pod_labels(instance, engine_chart)

    return get_pod_status_and_readiness(controller.namespace, pod_labels)


# Initialize the scheduler
scheduler = AsyncIOScheduler()

# Schedule the update_all_instance_endpoints function to run every 5 seconds
scheduler.add_job(update_all_instance_endpoints, 'interval', seconds=5)

# Start the scheduler
scheduler.start()
