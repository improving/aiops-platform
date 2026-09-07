import uuid

from fastapi import APIRouter, Depends, HTTPException
from kubernetes import client
from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib3.exceptions import MaxRetryError

from api.instance_inspection import InstanceKind, add_inspection_routes
from auth.current_user import CurrentUser, get_current_user, require_writer
from auth.policy import authorize_owner, authorize_write, owner_scope
from controller.notebooks_controller import NotebooksController
from db.database import get_db
from logger import setup_logger
from models.notebook import Notebook
from schemas.notebook import NotebookCreateSchema, NotebookInstanceSchema
from utils.gateway import gateway_settings, instance_url
from utils.instance_status import (
    STATUS_FAILED,
    STATUS_PENDING,
    apply_pod_status,
    mark_failed,
    refresh_stale,
)
from utils.kubernetes_utils import (
    get_pod_status_and_readiness,
    get_service_endpoint,
)

router = APIRouter()
logger = setup_logger(__name__)


def filter_notebook_fields(data: dict) -> dict:
    allowed_fields = {
        "id",
        "name",
        "namespace",
        "type",
        "framework",
        "nvidia_gpu",
        "image",
        "resources_cpu",
        "resources_memory",
        "resources_gpu",
        "storage_size",
        "service_type",
        "service_port",
        "created_at",
        "updated_at",
    }
    return {key: value for key, value in data.items() if key in allowed_fields}


@router.post("/v1alpha1/notebooks", response_model=NotebookInstanceSchema)
async def create_notebook(
    notebook: NotebookCreateSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    """
    Create a new notebook instance.

    Args:
        notebook (NotebookCreateSchema): The notebook instance data.

    Returns:
        NotebookInstanceSchema: The created notebook instance.

    Raises:
        HTTPException: 409 when a notebook with that name exists in the
            namespace, 500 when the Helm install fails.
    """
    existing = (
        db.query(Notebook)
        .filter(
            Notebook.name == notebook.name,
            Notebook.namespace == notebook.namespace,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Notebook '{notebook.name}' already exists",
        )

    notebook_data = filter_notebook_fields(notebook.model_dump())
    db_notebook = Notebook(
        **notebook_data,
        org_id=user.org_id,
        owner_id=user.id,
        status=STATUS_PENDING,
    )
    db.add(db_notebook)
    db.commit()
    db.refresh(db_notebook)
    try:
        controller = NotebooksController()
    except Exception as e:
        logger.exception(f"Failed to build the controller: {str(e)}")
        mark_failed(db, db_notebook, e)
        raise HTTPException(status_code=500, detail=str(e))

    try:
        await controller.install(db_notebook)
    except Exception as e:
        logger.exception(f"Failed to install Helm chart: {str(e)}")
        mark_failed(db, db_notebook, e)
        try:
            await controller.uninstall(db_notebook)
        except Exception:
            logger.exception(
                "Failed to uninstall the release of %s after a failed install",
                db_notebook.id,
            )
        raise HTTPException(status_code=500, detail=str(e))

    db.refresh(db_notebook)
    return db_notebook


@router.get("/v1alpha1/notebooks", response_model=list[NotebookInstanceSchema])
async def list_notebooks(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    List the notebook instances of the caller's organization.

    Returns:
        List[NotebookInstanceSchema]: A list of all notebook instances.

    Raises:
        HTTPException: If there's an error retrieving the notebook instances.
    """
    notebooks = db.query(Notebook).filter(owner_scope(Notebook, user)).all()
    try:
        for notebook in notebooks:
            notebook.ready, _ = check_pod_status_and_readiness(notebook, db)
    except MaxRetryError as e:
        logger.error(f"Error checking pod status and readiness: {e}")
        raise HTTPException(
            status_code=500, detail="Error checking pod status and readiness"
        )
    return notebooks


@router.get("/v1alpha1/notebooks/{id}", response_model=NotebookInstanceSchema)
async def get_notebook(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
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
    authorize_owner(user, notebook, "notebook")
    try:
        notebook.ready, _ = check_pod_status_and_readiness(notebook, db)
    except MaxRetryError as e:
        logger.error(f"Error checking pod status and readiness: {e}")
        raise HTTPException(
            status_code=500, detail="Error checking pod status and readiness"
        )
    return notebook


def _find_notebook(db: Session, id: uuid.UUID, user: CurrentUser) -> Notebook:
    notebook = (
        db.query(Notebook)
        .filter(Notebook.id == id)
        .filter(owner_scope(Notebook, user))
        .first()
    )
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return notebook


def notebook_pod_labels(controller: NotebooksController, notebook: Notebook):
    """The notebook-controller labels every pod with the Notebook CR name,
    which is the chart's Service name (see NotebooksController)."""
    return f"notebook-name={controller.get_service_name(notebook)}"


NOTEBOOK_KIND = InstanceKind(
    label="notebook",
    find=_find_notebook,
    # Notebooks are read by their owner only (owner_scope, authorize_owner).
    authorize_read=authorize_owner,
    authorize_write=authorize_write,
    make_controller=lambda db, row: NotebooksController(),
    namespace=lambda controller, row: row.namespace,
    pod_labels=lambda db, controller, row: notebook_pod_labels(
        controller, row
    ),
    # Notebooks have no actions (spec 6.3).
    restart=False,
)
add_inspection_routes(router, "/v1alpha1/notebooks", NOTEBOOK_KIND)


@router.put("/v1alpha1/notebooks/{id}", response_model=NotebookInstanceSchema)
async def update_notebook(
    id: uuid.UUID,
    notebook: NotebookInstanceSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
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
    authorize_write(user, db_notebook, "notebook")
    for key, value in filter_notebook_fields(notebook.model_dump()).items():
        setattr(db_notebook, key, value)
    db.commit()
    db.refresh(db_notebook)
    controller = NotebooksController()
    try:
        await controller.upgrade(db_notebook)
    except Exception as e:
        # The gateway may have deleted the browser route (fail closed):
        # the row must not keep saying Ready with an endpoint.
        logger.exception(f"Failed to upgrade the notebook: {str(e)}")
        mark_failed(db, db_notebook, e)
        raise HTTPException(
            status_code=500, detail=f"Failed to upgrade the notebook: {str(e)}"
        )
    return db_notebook


@router.delete("/v1alpha1/notebooks/{id}")
async def delete_notebook(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
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
    authorize_write(user, db_notebook, "notebook")
    # A Failed launch may have no release and no reachable cluster
    # behind it (the install failed before or while talking to
    # Kubernetes); its row must still be deletable, so for a Failed row
    # a controller or uninstall failure is logged, not fatal.
    failed = db_notebook.status == STATUS_FAILED
    controller = None
    try:
        controller = NotebooksController()
    except Exception as e:
        if not failed:
            raise
        logger.warning(
            f"Deleting failed notebook {id} without a controller: {e}"
        )
    if controller is not None:
        try:
            await controller.uninstall(db_notebook)
        except Exception as e:
            if not failed:
                raise
            logger.warning(
                f"Deleting failed notebook {id}; uninstall failed: {e}"
            )
    db.delete(db_notebook)
    db.commit()
    return {"message": "Notebook deleted successfully"}


def check_pod_status_and_readiness(
    instance: Notebook,
    db: Session,
    controller: NotebooksController | None = None,
):
    """Look at the pods, persist the derived status and return
    (ready, persisted status). The poller passes one controller for the
    whole tick; a request builds its own."""
    controller = (
        controller if controller is not None else NotebooksController()
    )
    pods = get_pod_status_and_readiness(
        instance.namespace, controller.get_pod_labels(instance)
    )
    apply_pod_status(db, instance, pods)
    return pods.ready, instance.status


def update_all_notebook_instance_endpoints(db: Session):
    """
    Update endpoints for all notebook instances that don't have populated endpoints.
    """
    logger.debug("Updating all instance endpoints")
    try:
        # Query for instances without populated endpoints
        instances = (
            db.query(Notebook)
            .filter(or_(Notebook.endpoint.is_(None), Notebook.endpoint == ""))
            .all()
        )

        logger.debug(
            f"Found {len(instances)} instances without populated endpoints"
        )

        for instance in instances:
            update_instance_endpoints(instance, db)

        refresh_stale(
            db, Notebook, check_pod_status_and_readiness, NotebooksController
        )
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

    if gateway_settings() is not None:
        # The hostname is deterministic, so the endpoint is set as soon as
        # the gateway is configured, without waiting for the Service.
        if instance.type == "jupyter":
            instance.endpoint = instance_url(
                "nb",
                instance.id,
                f"/notebook/{instance.namespace}/{service_name}/lab",
            )
        else:
            instance.endpoint = instance_url("nb", instance.id)
        db.commit()
        return

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
