from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from controller.finetune_controller import FinetuneController
from db.database import get_db
from logger import setup_logger
from repositories.finetune_repository import FinetuneRepository
from schemas.finetune import (FinetuneCreateSchema, FinetuneSchema,
                              FinetuneUpdateSchema)

router = APIRouter()
logger = setup_logger(__name__)
finetune_controller = FinetuneController()


@router.get("/v1alpha1/models/{model_id}/finetune",
            response_model=List[FinetuneSchema])
async def list_finetunes(model_id: UUID, db: Session = Depends(get_db)):
    """
    List all finetune jobs available in the cluster.

    Args:
        model_id (UUID): ID of the model.

    Returns:
        List[Finetune]: List of all finetune jobs.

    Raises:
        HTTPException: If there's an error retrieving the finetune jobs.
    """
    try:
        repository = FinetuneRepository(db)
        finetunes = repository.get_by_model_id(model_id)
        for finetune in finetunes:
            finetune.status = await finetune_controller.get_job_status(finetune
                                                                       )
        return finetunes
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Error retrieving finetune jobs: {str(e)}")


@router.post("/v1alpha1/models/{model_id}/finetune",
             response_model=FinetuneSchema,
             status_code=201)
async def create_finetune(model_id: UUID,
                          finetune: FinetuneCreateSchema,
                          db: Session = Depends(get_db)):
    """
    Create a new finetune job.

    Args:
        model_id (UUID): ID of the model.
        finetune (FinetuneCreate): Finetune job details.

    Returns:
        Finetune: Created finetune job.

    Raises:
        HTTPException: If there's an error creating the finetune job.
    """
    repository = FinetuneRepository(db)

    try:
        logger.info(f"Creating finetune job for model {model_id}")
        db_finetune = repository.create(model_id, finetune)

        # Submit Kubernetes job
        await finetune_controller.submit_job(db_finetune)
        db_finetune.status = "Created"

        return db_finetune
    except Exception as e:
        repository.delete(model_id, db_finetune.id)
        raise HTTPException(status_code=500,
                            detail=f"Error creating finetune job: {str(e)}")


@router.get("/v1alpha1/models/{model_id}/finetune/{finetune_id}",
            response_model=FinetuneSchema)
async def get_finetune(model_id: UUID,
                       finetune_id: UUID,
                       db: Session = Depends(get_db)):
    """
    Get details of a specific finetune job.

    Args:
        model_id (UUID): ID of the model.
        finetune_id (UUID): ID of the finetune job.

    Returns:
        Finetune: Details of the finetune job.

    Raises:
        HTTPException: If the finetune job is not found or there's an error retrieving it.
    """
    try:
        repository = FinetuneRepository(db)
        finetune = repository.get_by_id(model_id, finetune_id)
        if finetune is None:
            raise HTTPException(status_code=404,
                                detail="Finetune job not found")

        # Get Kubernetes job status
        finetune.status = await finetune_controller.get_job_status(finetune)

        return finetune
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Error retrieving finetune job: {str(e)}")


@router.put("/v1alpha1/models/{model_id}/finetune/{finetune_id}",
            response_model=FinetuneSchema)
async def update_finetune(model_id: UUID,
                          finetune_id: UUID,
                          finetune: FinetuneUpdateSchema,
                          db: Session = Depends(get_db)):
    """
    Update a finetune job.

    Args:
        model_id (UUID): ID of the model.
        finetune_id (UUID): ID of the finetune job to update.
        finetune (FinetuneUpdate): Updated finetune job details.

    Returns:
        Finetune: Updated finetune job.

    Raises:
        HTTPException: If the finetune job is not found or there's an error updating it.
    """
    try:
        repository = FinetuneRepository(db)
        updated_finetune = repository.update(model_id, finetune_id, finetune)
        if updated_finetune is None:
            raise HTTPException(status_code=404,
                                detail="Finetune job not found")

        # For now, we don't update the Kubernetes job
        # If needed, we can implement job update logic in the controller

        return updated_finetune
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Error updating finetune job: {str(e)}")


@router.delete("/v1alpha1/models/{model_id}/finetune/{finetune_id}",
               status_code=204)
async def delete_finetune(model_id: UUID,
                          finetune_id: UUID,
                          db: Session = Depends(get_db)):
    """
    Delete a finetune job.

    Args:
        model_id (UUID): ID of the model.
        finetune_id (UUID): ID of the finetune job to delete.

    Raises:
        HTTPException: If the finetune job is not found or there's an error deleting it.
    """
    try:
        repository = FinetuneRepository(db)
        finetune = repository.get_by_id(model_id, finetune_id)
        if not finetune:
            raise HTTPException(status_code=404,
                                detail="Finetune job not found")

        # Delete Kubernetes job
        await finetune_controller.delete_job(finetune)

        # Delete from database
        repository.delete(model_id, finetune_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Error deleting finetune job: {str(e)}")


@router.get("/v1alpha1/models/{model_id}/finetune/{finetune_id}/logs")
async def get_finetune_logs(model_id: UUID,
                            finetune_id: UUID,
                            db: Session = Depends(get_db)):
    """
    Get logs of a finetune job.

    Args:
        model_id (UUID): ID of the model.
        finetune_id (UUID): ID of the finetune job.

    Returns:
        str: Logs of the finetune job.

    Raises:
        HTTPException: If the finetune job is not found or there's an error retrieving logs.
    """
    try:
        repository = FinetuneRepository(db)
        finetune = repository.get_by_id(model_id, finetune_id)
        if not finetune:
            raise HTTPException(status_code=404,
                                detail="Finetune job not found")

        logs = await finetune_controller.get_job_logs(finetune)
        return {"logs": logs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving finetune job logs: {str(e)}")
