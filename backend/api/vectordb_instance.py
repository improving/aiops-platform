import uuid

from fastapi import APIRouter, Depends, HTTPException, Path
from kubernetes import client
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth.current_user import CurrentUser, get_current_user, require_writer
from auth.policy import authorize_read, authorize_write, org_scope
from controller.vectordb_controller import VectorDBController
from db.database import get_db
from logger import setup_logger
from models.vectordb import DBVectorDB
from models.vectordb_instance import DBVectorDBInstance
from models.workload_credential import KIND_VECTORDB
from schemas.vectordb import VectorDBSchema
from schemas.vectordb_instance import VectorDBInstanceSchema
from utils.credentials import (
    delete_credential,
    generate_secret,
    store_credential,
)
from utils.gateway import gateway_settings, instance_url
from utils.kubernetes_utils import (
    get_pod_status_and_readiness,
    get_service_endpoint,
)

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)


@router.get(
    "/v1alpha1/vectordb_instances", response_model=list[VectorDBInstanceSchema]
)
def list_vectordb_instances(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    List the vector database instances of the caller's organization.

    Returns:
        List[VectorDBInstanceSchema]: A list of all vector database instances.
    """
    vectordb_instances = (
        db.query(DBVectorDBInstance)
        .filter(org_scope(DBVectorDBInstance, user))
        .all()
    )
    for instance in vectordb_instances:
        instance_ready, instance_status = check_pod_status_and_readiness(
            instance
        )
        instance.ready = instance_ready
        instance.status = instance_status
    return vectordb_instances  # SQLAlchemy will handle the conversion


@router.get(
    "/v1alpha1/vectordb_instances/{id}", response_model=VectorDBInstanceSchema
)
def get_vectordb_instance(
    id: uuid.UUID = Path(
        description="The ID of the vector database instance to retrieve"
    ),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Retrieve a specific vector database instance by ID.

    Args:
        id (uuid.UUID): The ID of the vector database instance to retrieve.

    Returns:
        VectorDBInstanceSchema: The requested vector database instance.

    Raises:
        HTTPException: If the vector database instance is not found or there's an internal error.
    """
    try:
        vectordb_instance = (
            db.query(DBVectorDBInstance)
            .filter(DBVectorDBInstance.id == id)
            .first()
        )
        if not vectordb_instance:
            raise HTTPException(
                status_code=404, detail="Vector database instance not found"
            )
        authorize_read(user, vectordb_instance, "vector database instance")

        instance_ready, instance_status = check_pod_status_and_readiness(
            vectordb_instance
        )

        vectordb_instance.ready = instance_ready
        vectordb_instance.status = instance_status

        return vectordb_instance
    except HTTPException:
        logger.exception("HTTPException in get_vectordb_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in get_vectordb_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/v1alpha1/vectordb_instances",
    response_model=VectorDBInstanceSchema,
    status_code=201,
)
async def create_vectordb_instance(
    vectordb_instance: VectorDBInstanceSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    """
    Create a new vector database instance.

    Args:
        vectordb_instance (VectorDBInstanceSchema): The vector database instance data.

    Returns:
        VectorDBInstanceSchema: The created vector database instance.

    Raises:
        HTTPException: If there's an error creating the vector database instance.
    """
    dbVectorDB = (
        db.query(DBVectorDB)
        .filter(DBVectorDB.id == vectordb_instance.vectorDB.id)
        .first()
    )
    if not dbVectorDB:
        raise HTTPException(
            status_code=404, detail="Vector database not found"
        )

    # Build the controller before persisting anything: without a reachable
    # cluster it raises, and a row without a Helm release would be an orphan.
    try:
        controller = VectorDBController()
    except Exception as e:
        logger.exception("Kubernetes is not reachable")
        raise HTTPException(
            status_code=503, detail=f"Kubernetes is not reachable: {e}"
        ) from e

    dbVectorDBInstance = DBVectorDBInstance(
        vectordb_id=vectordb_instance.vectorDB.id,
        configParams=vectordb_instance.configParams,
        endpoint=vectordb_instance.endpoint,
        org_id=user.org_id,
        owner_id=user.id,
    )
    db.add(dbVectorDBInstance)
    db.commit()
    db.refresh(dbVectorDBInstance)

    instanceSchema = VectorDBInstanceSchema(
        id=dbVectorDBInstance.id,
        vectorDB=VectorDBSchema.model_validate(dbVectorDB),
        configParams=dbVectorDBInstance.configParams,
        endpoint=dbVectorDBInstance.endpoint,
    )

    logger.info(f"Instance schema: {instanceSchema}")

    # The API key: its Secrets are written before the install because the
    # chart reads them (see VectorDBController.install); the seed keeps
    # the value deterministic under TEST_MODE.
    try:
        value = generate_secret(seed=str(dbVectorDBInstance.id))
        store_credential(
            db,
            controller.namespace,
            KIND_VECTORDB,
            dbVectorDBInstance.id,
            value,
        )
        await controller.install(instanceSchema, credential=value)
    except Exception as e:
        logger.exception(f"Failed to install Helm chart: {str(e)}")
        try:
            delete_credential(
                db, controller.namespace, KIND_VECTORDB, dbVectorDBInstance.id
            )
        except Exception:
            logger.exception(
                "Failed to remove the credential of %s after a failed install",
                dbVectorDBInstance.id,
            )
        db.delete(dbVectorDBInstance)
        db.commit()
        raise HTTPException(
            status_code=500, detail=f"Failed to install Helm chart: {str(e)}"
        )

    return dbVectorDBInstance


@router.put(
    "/v1alpha1/vectordb_instances/{id}", response_model=VectorDBInstanceSchema
)
async def update_vectordb_instance(
    instanceSchema: VectorDBInstanceSchema,
    id: uuid.UUID = Path(
        description="The ID of the vector database instance to update"
    ),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Update an existing vector database instance.

    Args:
        id (uuid.UUID): The ID of the vector database instance to update.
        instanceSchema (VectorDBInstanceSchema): The updated vector database instance data.

    Returns:
        VectorDBInstanceSchema: The updated vector database instance.

    Raises:
        HTTPException: If the vector database instance is not found or there's an error during the update.
    """
    dbVectorDBInstance = (
        db.query(DBVectorDBInstance)
        .filter(DBVectorDBInstance.id == id)
        .first()
    )
    if not dbVectorDBInstance:
        raise HTTPException(
            status_code=404, detail="Vector database instance not found"
        )
    authorize_write(user, dbVectorDBInstance, "vector database instance")
    dbVectorDBInstance.vectordb_id = instanceSchema.vectorDB.id
    dbVectorDBInstance.configParams = instanceSchema.configParams
    dbVectorDBInstance.endpoint = None
    controller = VectorDBController()
    instanceSchema = VectorDBInstanceSchema(
        id=dbVectorDBInstance.id,
        vectorDB=VectorDBSchema.model_validate(dbVectorDBInstance.vectorDB),
        configParams=dbVectorDBInstance.configParams,
        endpoint=dbVectorDBInstance.endpoint,
    )

    try:
        await controller.upgrade(instanceSchema)
    except Exception as e:
        logger.exception(f"Failed to upgrade Helm chart: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to upgrade Helm chart: {str(e)}"
        )

    db.commit()
    db.refresh(dbVectorDBInstance)
    return dbVectorDBInstance


@router.delete("/v1alpha1/vectordb_instances/{id}", status_code=204)
async def delete_vectordb_instance(
    id: uuid.UUID = Path(
        description="The ID of the vector database instance to delete"
    ),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Delete a vector database instance.

    Args:
        id (uuid.UUID): The ID of the vector database instance to delete.

    Returns:
        dict: A message confirming the deletion.

    Raises:
        HTTPException: If the vector database instance is not found or there's an error during deletion.
    """
    dbVectorDBInstance = (
        db.query(DBVectorDBInstance)
        .filter(DBVectorDBInstance.id == id)
        .first()
    )
    if not dbVectorDBInstance:
        raise HTTPException(
            status_code=404, detail="Vector database instance not found"
        )
    authorize_write(user, dbVectorDBInstance, "vector database instance")

    controller = VectorDBController()
    instanceSchema = VectorDBInstanceSchema(
        id=dbVectorDBInstance.id,
        vectorDB=VectorDBSchema.model_validate(dbVectorDBInstance.vectorDB),
        configParams=dbVectorDBInstance.configParams,
        endpoint=dbVectorDBInstance.endpoint,
    )

    try:
        await controller.uninstall(instanceSchema)
    except Exception as e:
        logger.exception(f"Failed to uninstall Helm chart: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to uninstall Helm chart: {str(e)}"
        )

    # After the release and its policy: a failure here keeps the row, so
    # a retry uninstalls again (a missing release is not an error) and
    # deletes the Secrets.
    try:
        delete_credential(
            db, controller.namespace, KIND_VECTORDB, dbVectorDBInstance.id
        )
    except Exception as e:
        logger.exception(f"Failed to delete the credential: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to delete the credential Secrets: {str(e)}",
        )

    db.delete(dbVectorDBInstance)
    db.commit()
    return {"message": "Vector database instance deleted successfully"}


def check_pod_status_and_readiness(instance: DBVectorDBInstance):
    """
    Check the status and readiness of a vector database instance's pod.

    Args:
        instance (DBVectorDBInstance): The vector database instance to check.

    Returns:
        tuple: A tuple containing the readiness status and the pod status.
    """
    controller = VectorDBController()
    pod_labels = controller.get_pod_labels(instance)

    return get_pod_status_and_readiness(controller.namespace, pod_labels)


def update_all_vectordb_instance_endpoints(db: Session):
    """
    Update endpoints for all vector database instances that don't have populated endpoints.
    """
    logger.debug("Updating all instance endpoints")
    try:
        # Query for instances without populated endpoints
        instances = (
            db.query(DBVectorDBInstance)
            .filter(
                or_(
                    DBVectorDBInstance.endpoint.is_(None),
                    DBVectorDBInstance.endpoint == "",
                )
            )
            .all()
        )

        logger.debug(
            f"Found {len(instances)} instances without populated endpoints"
        )

        for instance in instances:
            update_instance_endpoints(instance, db)
    finally:
        db.close()


def update_instance_endpoints(instance: DBVectorDBInstance, db: Session):
    """
    Update the endpoints for a specific vector database instance.

    Args:
        instance (DBVectorDBInstance): The vector database instance to update.
    """
    logger.info(f"Updating endpoints for instance {instance.id}")
    controller = VectorDBController()
    service_name = controller.get_service_name(instance)

    if gateway_settings() is not None:
        # The hostnames are deterministic, so both endpoints are set as
        # soon as the gateway is configured, without waiting for the
        # Service.
        instance.endpoint = instance_url("vdb", instance.id)
        instance.api_endpoint = instance_url("vdb", instance.id, suffix="-api")
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
