import uuid
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, Path
from kubernetes import client
from sqlalchemy import JSON, UUID, Column, ForeignKey, String, or_
from sqlalchemy.orm import Session, relationship

from api.database import Base, SessionLocal, get_db
from api.kubernetes_utils import (get_pod_status_and_readiness,
                                  get_service_endpoint)
from api.vectordb import DBVectorDB
from controller.vectordb_controller import VectorDBController
from logger import setup_logger
from schemas.vectordb import VectorDBSchema
from schemas.vectordb_instance import VectorDBInstanceSchema

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)


# SQLAlchemy model
class DBVectorDBInstance(Base):
    __tablename__ = "vectordb_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vectordb_id = Column(UUID(as_uuid=True), ForeignKey('vectordb.id'))
    configParams = Column(JSON, nullable=True)  # Change this line
    endpoint = Column(String, nullable=True)

    vectorDB = relationship("DBVectorDB")


@router.get("/v1alpha1/vectordb_instances",
            response_model=List[VectorDBInstanceSchema])
def list_vectordb_instances(db: Session = Depends(get_db)):
    vectordb_instances = db.query(DBVectorDBInstance).all()
    for instance in vectordb_instances:
        instance_ready, instance_status = check_pod_status_and_readiness(
            instance)
        instance.ready = instance_ready
        instance.status = instance_status
    return vectordb_instances  # SQLAlchemy will handle the conversion


@router.get("/v1alpha1/vectordb_instances/{id}",
            response_model=VectorDBInstanceSchema)
def get_vectordb_instance(id: uuid.UUID = Path(
    description="The ID of the vector database instance to retrieve"),
                          db: Session = Depends(get_db)):
    try:
        vectordb_instance = db.query(DBVectorDBInstance).filter(
            DBVectorDBInstance.id == id).first()
        if not vectordb_instance:
            raise HTTPException(status_code=404,
                                detail="Vector database instance not found")

        instance_ready, instance_status = check_pod_status_and_readiness(
            vectordb_instance)

        vectordb_instance.ready = instance_ready
        vectordb_instance.status = instance_status

        return vectordb_instance
    except HTTPException:
        logger.exception("HTTPException in get_vectordb_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in get_vectordb_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/v1alpha1/vectordb_instances",
             response_model=VectorDBInstanceSchema,
             status_code=201)
async def create_vectordb_instance(vectordb_instance: VectorDBInstanceSchema,
                                   db: Session = Depends(get_db)):
    dbVectorDB = db.query(DBVectorDB).filter(
        DBVectorDB.id == vectordb_instance.vectorDB.id).first()
    if not dbVectorDB:
        raise HTTPException(status_code=404,
                            detail="Vector database not found")

    dbVectorDBInstance = DBVectorDBInstance(
        vectordb_id=vectordb_instance.vectorDB.id,
        configParams=vectordb_instance.configParams,
        endpoint=vectordb_instance.endpoint)
    db.add(dbVectorDBInstance)
    db.commit()
    db.refresh(dbVectorDBInstance)

    controller = VectorDBController()
    instanceSchema = VectorDBInstanceSchema(
        id=dbVectorDBInstance.id,
        vectorDB=VectorDBSchema.model_validate(dbVectorDB),
        configParams=dbVectorDBInstance.configParams,
        endpoint=dbVectorDBInstance.endpoint)

    logger.info(f"Instance schema: {instanceSchema}")

    try:
        await controller.install(instanceSchema)
    except Exception as e:
        db.delete(dbVectorDBInstance)
        db.commit()
        logger.exception(f"Failed to install Helm chart: {str(e)}")
        raise HTTPException(status_code=500,
                            detail=f"Failed to install Helm chart: {str(e)}")

    return dbVectorDBInstance


@router.put("/v1alpha1/vectordb_instances/{id}",
            response_model=VectorDBInstanceSchema)
async def update_vectordb_instance(
    instanceSchema: VectorDBInstanceSchema,
    id: uuid.UUID = Path(
        description="The ID of the vector database instance to update"),
    db: Session = Depends(get_db)):
    dbVectorDBInstance = db.query(DBVectorDBInstance).filter(
        DBVectorDBInstance.id == id).first()
    if not dbVectorDBInstance:
        raise HTTPException(status_code=404,
                            detail="Vector database instance not found")
    dbVectorDBInstance.vectordb_id = instanceSchema.vectorDB.id
    dbVectorDBInstance.configParams = instanceSchema.configParams
    dbVectorDBInstance.endpoint = None
    controller = VectorDBController()
    instanceSchema = VectorDBInstanceSchema(
        id=dbVectorDBInstance.id,
        vectorDB=VectorDBSchema.model_validate(dbVectorDBInstance.vectorDB),
        configParams=dbVectorDBInstance.configParams,
        endpoint=dbVectorDBInstance.endpoint)

    try:
        await controller.upgrade(instanceSchema)
    except Exception as e:
        logger.exception(f"Failed to upgrade Helm chart: {str(e)}")
        raise HTTPException(status_code=500,
                            detail=f"Failed to upgrade Helm chart: {str(e)}")

    db.commit()
    db.refresh(dbVectorDBInstance)
    return dbVectorDBInstance


@router.delete("/v1alpha1/vectordb_instances/{id}", status_code=204)
async def delete_vectordb_instance(id: uuid.UUID = Path(
    description="The ID of the vector database instance to delete"),
                                   db: Session = Depends(get_db)):
    dbVectorDBInstance = db.query(DBVectorDBInstance).filter(
        DBVectorDBInstance.id == id).first()
    if not dbVectorDBInstance:
        raise HTTPException(status_code=404,
                            detail="Vector database instance not found")

    controller = VectorDBController()
    instanceSchema = VectorDBInstanceSchema(
        id=dbVectorDBInstance.id,
        vectorDB=VectorDBSchema.model_validate(dbVectorDBInstance.vectorDB),
        configParams=dbVectorDBInstance.configParams,
        endpoint=dbVectorDBInstance.endpoint)

    try:
        await controller.uninstall(instanceSchema)
    except Exception as e:
        logger.exception(f"Failed to uninstall Helm chart: {str(e)}")
        raise HTTPException(status_code=500,
                            detail=f"Failed to uninstall Helm chart: {str(e)}")

    db.delete(dbVectorDBInstance)
    db.commit()
    return {"message": "Vector database instance deleted successfully"}


def check_pod_status_and_readiness(instance: DBVectorDBInstance):
    controller = VectorDBController()
    pod_labels = controller.get_pod_labels(instance)

    return get_pod_status_and_readiness(controller.namespace, pod_labels)


def update_all_instance_endpoints():
    logger.debug("Updating all instance endpoints")
    db = SessionLocal()
    try:
        # Query for instances without populated endpoints
        instances = db.query(DBVectorDBInstance).filter(
            or_(DBVectorDBInstance.endpoint.is_(None),
                DBVectorDBInstance.endpoint == '')).all()

        logger.debug(
            f"Found {len(instances)} instances without populated endpoints")

        for instance in instances:
            update_instance_endpoints(instance, db)
    finally:
        db.close()


def update_instance_endpoints(instance: DBVectorDBInstance, db: Session):
    logger.info(f"Updating endpoints for instance {instance.id}")
    controller = VectorDBController()
    service_name = controller.get_service_name(instance)

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


# Initialize the scheduler
scheduler = AsyncIOScheduler()

# Schedule the update_all_instance_endpoints function to run every 5 seconds
scheduler.add_job(update_all_instance_endpoints, 'interval', seconds=5)

# Start the scheduler
scheduler.start()
