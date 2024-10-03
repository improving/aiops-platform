import uuid
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException
from kubernetes import client
from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib3.exceptions import MaxRetryError

from controller.notebooks_controller import NotebooksController
from db.database import SessionLocal, get_db
from logger import setup_logger
from models.notebook import Notebook
from schemas.notebook import NotebookInstanceSchema
from utils.kubernetes_utils import (get_pod_status_and_readiness,
                                    get_service_endpoint)

router = APIRouter()
logger = setup_logger(__name__)


def filter_notebook_fields(data: dict) -> dict:
    allowed_fields = {
        'id', 'name', 'namespace', 'type', 'framework', 'nvidia_gpu', 'image',
        'resources_cpu', 'resources_memory', 'resources_gpu', 'storage_size',
        'service_type', 'service_port', 'created_at', 'updated_at'
    }
    return {key: value for key, value in data.items() if key in allowed_fields}


@router.post("/v1alpha1/notebooks", response_model=NotebookInstanceSchema)
async def create_notebook(notebook: NotebookInstanceSchema,
                          db: Session = Depends(get_db)):
    """
    Create a new notebook instance.

    Args:
        notebook (NotebookInstanceSchema): The notebook instance data.

    Returns:
        NotebookInstanceSchema: The created notebook instance.

    Raises:
        HTTPException: If there's an error creating the notebook instance.
    """
    notebook_data = filter_notebook_fields(notebook.model_dump())
    db_notebook = Notebook(**notebook_data)
    controller = NotebooksController()
    try:
        await controller.install(db_notebook)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.add(db_notebook)
    db.commit()
    db.refresh(db_notebook)
    return db_notebook


@router.get("/v1alpha1/notebooks", response_model=List[NotebookInstanceSchema])
async def list_notebooks(db: Session = Depends(get_db)):
    """
    List all notebook instances.

    Returns:
        List[NotebookInstanceSchema]: A list of all notebook instances.

    Raises:
        HTTPException: If there's an error retrieving the notebook instances.
    """
    notebooks = db.query(Notebook).all()
    try:
        for notebook in notebooks:
            notebook.ready, notebook.status = check_pod_status_and_readiness(
                notebook)
    except MaxRetryError as e:
        logger.error(f"Error checking pod status and readiness: {e}")
        raise HTTPException(status_code=500,
                            detail="Error checking pod status and readiness")
    return notebooks


@router.get("/v1alpha1/notebooks/{id}", response_model=NotebookInstanceSchema)
async def get_notebook(id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Retrieve a specific notebook instance by ID.

    Args:
        id (uuid.UUID): The ID of the notebook instance to retrieve.

    Returns:
        NotebookInstanceSchema: The requested notebook instance.

    Raises:
        HTTPException: If the notebook is not found or there's an error checking its status.
    """
    notebook = db.query(Notebook).filter(Notebook.id == id).first()
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    try:
        notebook.ready, notebook.status = check_pod_status_and_readiness(
            notebook)
    except MaxRetryError as e:
        logger.error(f"Error checking pod status and readiness: {e}")
        raise HTTPException(status_code=500,
                            detail="Error checking pod status and readiness")
    return notebook


@router.put("/v1alpha1/notebooks/{id}", response_model=NotebookInstanceSchema)
async def update_notebook(id: uuid.UUID,
                          notebook: NotebookInstanceSchema,
                          db: Session = Depends(get_db)):
    """
    Update an existing notebook instance.

    Args:
        id (uuid.UUID): The ID of the notebook instance to update.
        notebook (NotebookInstanceSchema): The updated notebook instance data.

    Returns:
        NotebookInstanceSchema: The updated notebook instance.

    Raises:
        HTTPException: If the notebook is not found.
    """
    db_notebook = db.query(Notebook).filter(Notebook.id == id).first()
    if not db_notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    for key, value in filter_notebook_fields(notebook.model_dump()).items():
        setattr(db_notebook, key, value)
    db.commit()
    db.refresh(db_notebook)
    controller = NotebooksController()
    await controller.upgrade(db_notebook)
    return db_notebook


@router.delete("/v1alpha1/notebooks/{id}")
async def delete_notebook(id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Delete a notebook instance.

    Args:
        id (uuid.UUID): The ID of the notebook instance to delete.

    Returns:
        dict: A message confirming the deletion.

    Raises:
        HTTPException: If the notebook is not found.
    """
    db_notebook = db.query(Notebook).filter(Notebook.id == id).first()
    if not db_notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    controller = NotebooksController()
    await controller.uninstall(db_notebook)
    db.delete(db_notebook)
    db.commit()
    return {"message": "Notebook deleted successfully"}


def check_pod_status_and_readiness(instance: Notebook):
    """
    Check the status and readiness of a notebook instance's pod.

    Args:
        instance (Notebook): The notebook instance to check.

    Returns:
        tuple: A tuple containing the readiness status and the pod status.
    """
    controller = NotebooksController()
    pod_labels = controller.get_pod_labels(instance)
    return get_pod_status_and_readiness(instance.namespace, pod_labels)


def update_all_instance_endpoints():
    """
    Update endpoints for all notebook instances that don't have populated endpoints.
    """
    logger.debug("Updating all instance endpoints")
    db = SessionLocal()
    try:
        # Query for instances without populated endpoints
        instances = db.query(Notebook).filter(
            or_(Notebook.endpoint.is_(None), Notebook.endpoint == '')).all()

        logger.debug(
            f"Found {len(instances)} instances without populated endpoints")

        for instance in instances:
            update_instance_endpoints(instance, db)
    finally:
        db.close()


def update_instance_endpoints(instance: Notebook, db: Session):
    """
    Update the endpoints for a specific notebook instance.

    Args:
        instance (Notebook): The notebook instance to update.
    """
    logger.info(f"Updating endpoints for instance {instance.id}")
    controller = NotebooksController()
    service_name = controller.get_service_name(instance)

    try:
        endpoint = get_service_endpoint(instance.namespace, service_name)

        if endpoint:
            # Update the instance endpoint
            instance.endpoint = endpoint

            if instance.type == "jupyter":
                instance.endpoint = f"{endpoint}/notebook/{instance.namespace}/{service_name}/lab"

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
