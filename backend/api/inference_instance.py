import os
import traceback
from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, and_, or_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, relationship
from sqlalchemy.future import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from api.engine_chart_dashboards import DBEngineChartDashboards
from api.engine_charts import DBEngineCharts
from api.inference_instance_dashboards import InferenceInstanceDashboards
from logger import setup_logger

from controller.base_controller import Controller
from schemas.inference_instance_dashboards import InferenceInstanceDashboardsSchema
from .database import Base, get_db
from .models import DBModel
from .engines import DBEngine
from .controller_utils import get_controller
from schemas.inference_instance import InferenceInstanceSchema, InferenceInstanceConfigParamsSchema
from schemas.model import ModelSchema
from schemas.engine import EngineSchema
from kubernetes import client
from api.database import SessionLocal
from .kubernetes_utils import load_kubernetes_config

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)

# Static org_id for all dashboards
org_id = "1"

# SQLAlchemy models
class DBInferenceInstanceConfigParams(Base):
    __tablename__ = "inference_instance_config_params"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maxInputLength = Column(Integer)
    maxTokens = Column(Integer)
    maxBatchPrefillTokens = Column(Integer)
    maxBatchTotalTokens = Column(Integer)
    quantization = Column(String)
    image = Column(String)

class DBInferenceInstance(Base):
    __tablename__ = "inference_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id = Column(UUID(as_uuid=True), ForeignKey('models.id'))
    engine_id = Column(UUID(as_uuid=True), ForeignKey('engines.id'))
    host = Column(String)
    endpoint = Column(String)
    healthEndpoint = Column(String)
    metricsEndpoint = Column(String)
    config_id = Column(UUID(as_uuid=True), ForeignKey('inference_instance_config_params.id'))

    model = relationship("DBModel")
    engine = relationship("DBEngine")
    config = relationship("DBInferenceInstanceConfigParams")

@router.get("/v1alpha1/inferenceInstance", response_model=List[InferenceInstanceSchema])
async def list_inference_instances(db: Session = Depends(get_db)):
    try:
        instances = db.query(DBInferenceInstance).all()
        config_source = load_kubernetes_config()
        logger.info(f"Loaded Kubernetes configuration from: {config_source}")
        core_v1_api = client.CoreV1Api()
        for instance in instances:
            instance_ready, instance_status = await check_pod_status_and_readiness(instance, core_v1_api, db)
            instance.ready = instance_ready
            instance.status = instance_status
        return instances
    except Exception as e:
        logger.exception(f"Error in list_inference_instances: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstanceSchema)
async def get_inference_instance(id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        instance = db.query(DBInferenceInstance).filter(DBInferenceInstance.id == id).first()
        if not instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(status_code=404, detail="Inference instance not found")

        config_source = load_kubernetes_config()
        logger.info(f"Loaded Kubernetes configuration from: {config_source}")
        core_v1_api = client.CoreV1Api()

        instance_ready, instance_status = await check_pod_status_and_readiness(instance, core_v1_api, db)

        full_instance = InferenceInstanceSchema(
            id=instance.id,
            model=ModelSchema.model_validate(instance.model),
            engine=EngineSchema.model_validate(instance.engine),
            host=instance.host,
            config=InferenceInstanceConfigParamsSchema.model_validate(instance.config) if instance.config else None,
            endpoint=instance.endpoint,
            healthEndpoint=instance.healthEndpoint,
            metricsEndpoint=instance.metricsEndpoint,
            ready=instance_ready,
            status=instance_status
        )

        return full_instance
    except HTTPException:
        logger.exception("HTTPException in get_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in get_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/v1alpha1/inferenceInstance/{id}/dashboards", response_model=List[InferenceInstanceDashboardsSchema])
async def get_inference_instance_dashboards(id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        db_instance_dashboards = db.query(InferenceInstanceDashboards).filter(InferenceInstanceDashboards.inference_instance_id == id).all()

        if not db_instance_dashboards:
            return []
        
        instance_dashboard_list = []
        for db_instance_dashboard in db_instance_dashboards:
            instance_dashboard = InferenceInstanceDashboardsSchema(
                id=db_instance_dashboard.id,
                org_id=db_instance_dashboard.org_id,
                query_params=db_instance_dashboard.query_params
            )
            chart_dashboard = db.query(DBEngineChartDashboards).filter(DBEngineChartDashboards.id == db_instance_dashboard.engine_chart_dashboard_id).first()
            if chart_dashboard:
                instance_dashboard.dashboard_id = chart_dashboard.dashboard_id
                instance_dashboard.dashboard_name = chart_dashboard.dashboard_name
                instance_dashboard.panel_id = chart_dashboard.panel_id
                instance_dashboard.panel_name = chart_dashboard.panel_name
            instance_dashboard_list.append(instance_dashboard)

        return instance_dashboard_list
    except Exception as e:
        logger.exception(f"Error in get_inference_instance_dashboards: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/v1alpha1/inferenceInstance", response_model=InferenceInstanceSchema)
async def create_inference_instance(instance: InferenceInstanceSchema, db: Session = Depends(get_db)):
    try:
        model = db.query(DBModel).filter(DBModel.id == instance.model.id).first()
        engine = db.query(DBEngine).filter(DBEngine.id == instance.engine.id).first()
        
        if not model or not engine:
            logger.error(f"Model or Engine not found: model_id={instance.model.id}, engine_id={instance.engine.id}")
            raise HTTPException(status_code=404, detail="Model or Engine not found")
        
        engine_chart = db.query(DBEngineCharts).filter(and_(DBEngineCharts.engine == engine.name, DBEngineCharts.chart_type == model.category)).first()
        if not engine_chart:
            logger.error(f"Model Engine combination is invalid: model: {model.name}, engine: {engine.name}")

        HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
        NGC_API_KEY = os.environ.get("NGC_API_KEY")

        if engine.name == 'nim' and not NGC_API_KEY:
            logger.error("NGC API key not set")
            raise HTTPException(status_code=400, detail="NGC API key not set")
        elif not HF_API_TOKEN:
            logger.error("HuggingFace API token not set")
            raise HTTPException(status_code=400, detail="HuggingFace API token not set.")

        config_data = instance.config.dict() if instance.config else {}
        db_config = DBInferenceInstanceConfigParams(**config_data)
        
        db_instance = DBInferenceInstance(
            model_id=instance.model.id,
            engine_id=instance.engine.id,
            host=instance.host,
            endpoint=instance.endpoint or "",
            healthEndpoint=instance.healthEndpoint or "",
            metricsEndpoint=instance.metricsEndpoint or "",
            config=db_config
        )
        db.add(db_config)
        db.add(db_instance)
        db.commit()
        db.refresh(db_instance)

        full_instance = InferenceInstanceSchema(
            id=db_instance.id,
            model=ModelSchema.model_validate(model),
            engine=EngineSchema.model_validate(engine),
            host=db_instance.host,
            config=InferenceInstanceConfigParamsSchema.model_validate(db_config) if db_config else None,
            endpoint=db_instance.endpoint,
            healthEndpoint=db_instance.healthEndpoint,
            metricsEndpoint=db_instance.metricsEndpoint
        )

        controller = await get_controller(engine.name)

        try:
            await controller.install(full_instance, engine_chart)
        except Exception as e:
            db.delete(db_instance)
            db.delete(db_config)
            db.commit()
            logger.exception(f"Failed to install Helm chart: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to install Helm chart: {str(e)}")
        
        try:
            await create_instance_dashboards(full_instance, engine_chart, db)
        except Exception as e:
            logger.exception(f"Failed to create dashboards: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create dashboards: {str(e)}")

        return full_instance
    except HTTPException:
        logger.exception("HTTPException in create_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in create_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.patch("/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstanceSchema)
async def update_inference_instance(id: uuid.UUID, updated_instance: InferenceInstanceSchema, db: Session = Depends(get_db)):
    try:
        db_instance = db.query(DBInferenceInstance).filter(DBInferenceInstance.id == id).first()
        if not db_instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(status_code=404, detail="Inference instance not found")

        for key, value in updated_instance.dict(exclude_unset=True).items():
            if key == 'config':
                for config_key, config_value in value.items():
                    setattr(db_instance.config, config_key, config_value)
            else:
                setattr(db_instance, key, value)

        db.commit()
        db.refresh(db_instance)

        model = db.query(DBModel).filter(DBModel.id == db_instance.model_id).first()
        engine = db.query(DBEngine).filter(DBEngine.id == db_instance.engine_id).first()
        engine_chart = db.query(DBEngineCharts).filter(and_(DBEngineCharts.engine == engine.name, DBEngineCharts.chart_type == model.category)).first()

        full_instance = InferenceInstanceSchema(
            id=db_instance.id,
            model=ModelSchema.model_validate(model),
            engine=EngineSchema.model_validate(engine),
            host=db_instance.host,
            config=InferenceInstanceConfigParamsSchema.model_validate(db_instance.config) if db_instance.config else None,
            endpoint=db_instance.endpoint,
            healthEndpoint=db_instance.healthEndpoint,
            metricsEndpoint=db_instance.metricsEndpoint
        )

        controller = await get_controller(engine.name)

        try:
            await controller.upgrade(full_instance, engine_chart)
        except Exception as e:
            logger.exception(f"Failed to upgrade Helm chart: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to upgrade Helm chart: {str(e)}")

        return db_instance
    except HTTPException:
        logger.exception("HTTPException in update_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in update_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/v1alpha1/inferenceInstance/{id}")
async def delete_inference_instance(id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        db_instance = db.query(DBInferenceInstance).filter(DBInferenceInstance.id == id).first()
        if not db_instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(status_code=404, detail="Inference instance not found")

        model = db.query(DBModel).filter(DBModel.id == db_instance.model_id).first()
        engine = db.query(DBEngine).filter(DBEngine.id == db_instance.engine_id).first()
        engine_chart = db.query(DBEngineCharts).filter(and_(DBEngineCharts.engine == engine.name, DBEngineCharts.chart_type == model.category)).first()
        instance_dashboards = db.query(InferenceInstanceDashboards).filter(InferenceInstanceDashboards.inference_instance_id == id).all()

        full_instance = InferenceInstanceSchema(
            id=db_instance.id,
            model=ModelSchema.model_validate(model),
            engine=EngineSchema.model_validate(engine),
            host=db_instance.host,
            config=InferenceInstanceConfigParamsSchema.model_validate(db_instance.config) if db_instance.config else None,
            endpoint=db_instance.endpoint,
            healthEndpoint=db_instance.healthEndpoint,
            metricsEndpoint=db_instance.metricsEndpoint
        )

        controller = await get_controller(engine.name)

        try:
            await controller.uninstall(full_instance, engine_chart)
        except Exception as e:
            logger.exception(f"Failed to remove Helm chart: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to remove Helm chart: {str(e)}")

        db.delete(db_instance.config)
        db.delete(db_instance)
        db.commit()

        try:
            if instance_dashboards:
                for dashboard in instance_dashboards:
                    db.delete(dashboard)
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

async def create_instance_dashboards(instance: InferenceInstanceSchema, engine_chart: DBEngineCharts, db: Session):
    try:
        engine_chart_dashboards = db.query(DBEngineChartDashboards).filter(and_(DBEngineChartDashboards.engine_id == instance.engine.id, 
                                                                                DBEngineChartDashboards.engine_chart_id == engine_chart.id)).all()
        if not engine_chart_dashboards:
            logger.error(f"No dashboards found for engine chart: {engine_chart.id}")
            return

        for chart_dashboard in engine_chart_dashboards:
            controller = await get_controller(instance.engine.name)
            namespace = controller.namespace
            service_name = controller._get_service_name(instance, engine_chart)
            query_params = {
                "var-namespace": namespace,
                "var-service": service_name,
            }
            inference_instance_dashboard = InferenceInstanceDashboards(
                id = uuid.uuid4(),
                inference_instance_id=instance.id,
                engine_chart_dashboard_id=chart_dashboard.id,
                org_id=org_id,
                query_params=str(query_params)
            )
            db.add(inference_instance_dashboard)
        
        db.commit()
    except Exception as e:
        logger.exception(f"Error creating instance dashboards: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating instance dashboards: {e}")

async def update_all_instance_endpoints():
    db = SessionLocal()
    try:
        # Query for instances without populated endpoints
        instances = db.query(DBInferenceInstance).filter(or_(DBInferenceInstance.endpoint == None, DBInferenceInstance.endpoint == '')).all()

        for instance in instances:
            await update_instance_endpoints(instance, db)
    finally:
        db.close()

async def update_instance_endpoints(instance: DBInferenceInstance, db: Session):
    logger.info(f"Updating endpoints for instance {instance.id}")
    engine = db.query(DBEngine).filter(DBEngine.id == instance.engine_id).first()
    if not engine:
        raise HTTPException(status_code=404, detail="Associated engine not found")
    
    engine_chart = db.query(DBEngineCharts).filter(and_(DBEngineCharts.engine == engine.name, DBEngineCharts.chart_type == instance.model.category)).first()
    if not engine_chart:
        raise HTTPException(status_code=404, detail="Associated engine chart not found")

    controller = await get_controller(engine.name)
    service_name = controller._get_service_name(instance, engine_chart)

    config_source = load_kubernetes_config()
    logger.info(f"Loaded Kubernetes configuration from: {config_source}")
    core_v1_api = client.CoreV1Api()

    try:
        # Get the service information
        service = core_v1_api.read_namespaced_service(name=service_name, namespace=controller.namespace)

        # Get the service IP and port
        if service.spec.type == "LoadBalancer":
            ip = service.status.load_balancer.ingress[0].ip if service.status.load_balancer.ingress else None
        else:
            ip = service.spec.cluster_ip

        port = service.spec.ports[0].port if service.spec.ports else None

        if ip and port:
            # Update the instance endpoint
            instance.endpoint = f"http://{ip}:{port}"
            instance.healthEndpoint = f"http://{ip}:{port}/health"
            instance.metricsEndpoint = f"http://{ip}:{port}/metrics"

            # Update the database
            db.commit()
        else:
            logger.warning(f"Warning: Could not determine IP or port for service {service_name}")

    except client.exceptions.ApiException as e:
        logger.exception(f"Error getting service information: {e}")
    # Don't raise an exception here, as we still want to return the instance information

async def check_pod_status_and_readiness(instance: DBInferenceInstance, core_v1_api: client.CoreV1Api, db: Session):
    # Get the associated engine
    engine = db.query(DBEngine).filter(DBEngine.id == instance.engine_id).first()
    if not engine:
        raise HTTPException(status_code=404, detail="Associated engine not found")
    
    engine_chart = db.query(DBEngineCharts).filter(and_(DBEngineCharts.engine == engine.name, DBEngineCharts.chart_type == instance.model.category)).first()
    if not engine_chart:
        raise HTTPException(status_code=404, detail="Associated engine chart not found")

    controller = await get_controller(engine.name)

    # Check pod readiness
    try:
        # Define pod labels based on the engine type
        pod_labels = controller._get_pod_labels(instance, engine_chart)

        # Query pods
        pods = core_v1_api.list_namespaced_pod(namespace=controller.namespace, label_selector=pod_labels)

        # Check if any pod is ready
        instance_ready = any(
            pod.status.phase == 'Running' and 
            all(container.ready for container in pod.status.container_statuses)
            for pod in pods.items
        )

        if pods.items:
            pod = pods.items[0]
            status = pod.status.container_statuses[0]
            if pod.status.init_container_statuses:
                initContainerStatus = pod.status.init_container_statuses[0]
                if not initContainerStatus.state.terminated:
                    logger.info(f"Using init container status")
                    status = initContainerStatus
                else:
                    logger.info(f"Using container status")

            logger.info(f"Pod Name: {pod.metadata.name}, Status: {status}")
            if not status.started and status.state.waiting:
                instance_status = status.state.waiting.reason
            elif not status.started and status.state.terminated:
                instance_status = "Terminated"
            elif status.started or (not status.started and status.state.running.started_at):
                instance_status = "Running"
            else:
                instance_status = status.state
        else:
            instance_status = "Unknown"
    except client.exceptions.ApiException as e:
        logger.exception(f"Error checking pod status and readiness: {e}")
        instance_ready = False
        instance_status = "Unknown"

    return instance_ready, instance_status
    

# Initialize the scheduler
scheduler = AsyncIOScheduler()

# Schedule the update_all_instance_endpoints function to run every 5 seconds
scheduler.add_job(update_all_instance_endpoints, 'interval', seconds=5)

# Start the scheduler
scheduler.start()
