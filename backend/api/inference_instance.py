import os
import traceback
from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, or_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, relationship
from sqlalchemy.future import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from logger import setup_logger

from controller.base_controller import Controller
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
            instance_ready = await check_pod_readiness(instance, core_v1_api, db)
            instance.ready = instance_ready
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

        instance_ready = await check_pod_readiness(instance, core_v1_api, db)

        full_instance = InferenceInstanceSchema(
            id=instance.id,
            model=ModelSchema.model_validate(instance.model),
            engine=EngineSchema.model_validate(instance.engine),
            host=instance.host,
            config=InferenceInstanceConfigParamsSchema.model_validate(instance.config) if instance.config else None,
            endpoint=instance.endpoint,
            healthEndpoint=instance.healthEndpoint,
            metricsEndpoint=instance.metricsEndpoint,
            ready=instance_ready
        )

        return full_instance
    except HTTPException:
        logger.exception("HTTPException in get_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in get_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/v1alpha1/inferenceInstance", response_model=InferenceInstanceSchema)
async def create_inference_instance(instance: InferenceInstanceSchema, db: Session = Depends(get_db)):
    try:
        model = db.query(DBModel).filter(DBModel.id == instance.model.id).first()
        engine = db.query(DBEngine).filter(DBEngine.id == instance.engine.id).first()
        
        if not model or not engine:
            logger.error(f"Model or Engine not found: model_id={instance.model.id}, engine_id={instance.engine.id}")
            raise HTTPException(status_code=404, detail="Model or Engine not found")

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
            await controller.install(full_instance)
        except Exception as e:
            db.delete(db_instance)
            db.delete(db_config)
            db.commit()
            logger.exception(f"Failed to install Helm chart: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to install Helm chart: {str(e)}")

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

        controller = await get_controller(db_instance.engine.name)

        try:
            await controller.upgrade(db_instance)
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

        controller = await get_controller(db_instance.engine.name)

        try:
            await controller.remove(db_instance)
        except Exception as e:
            logger.exception(f"Failed to remove Helm chart: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to remove Helm chart: {str(e)}")

        db.delete(db_instance.config)
        db.delete(db_instance)
        db.commit()

        return {"detail": "Inference instance deleted"}
    except HTTPException:
        logger.exception("HTTPException in delete_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in delete_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

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

    controller = await get_controller(engine.name)
    service_name = controller._get_service_name(instance)

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

async def check_pod_readiness(instance: DBInferenceInstance, core_v1_api: client.CoreV1Api, db: Session):
    # Get the associated engine
    engine = db.query(DBEngine).filter(DBEngine.id == instance.engine_id).first()
    if not engine:
        raise HTTPException(status_code=404, detail="Associated engine not found")

    controller = await get_controller(engine.name)

    # Check pod readiness
    try:
        # Define pod labels based on the engine type
        pod_labels = controller._get_pod_labels(instance)

        # Query pods
        pods = core_v1_api.list_namespaced_pod(namespace=controller.namespace, label_selector=pod_labels)

        # Check if any pod is ready
        instance_ready = any(
            pod.status.phase == 'Running' and 
            all(container.ready for container in pod.status.container_statuses)
            for pod in pods.items
        )
    except client.exceptions.ApiException as e:
        logger.exception(f"Error checking pod readiness: {e}")
        instance_ready = False
    
    return instance_ready
    

# Initialize the scheduler
scheduler = AsyncIOScheduler()

# Schedule the update_all_instance_endpoints function to run every 5 seconds
scheduler.add_job(update_all_instance_endpoints, 'interval', seconds=5)

# Start the scheduler
scheduler.start()
