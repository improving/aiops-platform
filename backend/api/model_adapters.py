import traceback
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.database import get_db
from logger import setup_logger
from models.model_adapters import DBModelAdapters
from schemas.model import ModelSchema
from schemas.model_adapters import ModelAdapterSchema

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)


# Helper function to convert DBModelAdapters to ModelAdapterSchema
def db_to_schema(db_adapter: DBModelAdapters) -> ModelAdapterSchema:
    return ModelAdapterSchema(id=db_adapter.id,
                              name=db_adapter.name,
                              base_model=ModelSchema.model_validate(
                                  db_adapter.base_model),
                              path=db_adapter.path,
                              hf_id=db_adapter.hf_id)


# Helper function to get a model adapter by ID
def get_model_adapter(db: Session, model_id: UUID, adapter_id: UUID):
    adapter = db.query(DBModelAdapters).filter(
        DBModelAdapters.id == adapter_id,
        DBModelAdapters.model_id == model_id).first()
    if adapter is None:
        raise HTTPException(status_code=404, detail="Model adapter not found")
    return adapter


@router.get("/v1alpha1/model/{model_id}/adapters/{adapter_id}",
            response_model=ModelAdapterSchema)
def get_model_adapter_api(model_id: UUID,
                          adapter_id: UUID,
                          db: Session = Depends(get_db)):
    db_adapter = get_model_adapter(db, model_id, adapter_id)
    return db_to_schema(db_adapter)


@router.get("/v1alpha1/model/{model_id}/adapters",
            response_model=List[ModelAdapterSchema])
def list_model_adapters(model_id: UUID, db: Session = Depends(get_db)):
    db_adapters = db.query(DBModelAdapters).filter(
        DBModelAdapters.model_id == model_id).all()
    return [db_to_schema(adapter) for adapter in db_adapters]


@router.post("/v1alpha1/model/{model_id}/adapters",
             response_model=ModelAdapterSchema,
             status_code=201)
def create_model_adapter(model_id: UUID,
                         adapter: ModelAdapterSchema,
                         db: Session = Depends(get_db)):
    if adapter.base_model and model_id != adapter.base_model.id:
        raise HTTPException(
            status_code=400,
            detail=
            "Model ID in the adapter does not match the model ID in the path")
    if not adapter.path and not adapter.hf_id:
        raise HTTPException(status_code=400,
                            detail="Either path or hf_id must be specified")
    db_adapter = DBModelAdapters(name=adapter.name,
                                 model_id=model_id,
                                 path=adapter.path,
                                 hf_id=adapter.hf_id)
    try:
        db.add(db_adapter)
        db.commit()
        db.refresh(db_adapter)
    except IntegrityError as e:
        db.rollback()
        if 'uq_model_adapter_name' in str(e):
            raise HTTPException(
                status_code=400,
                detail=
                "Model adapter with this name already exists for the given model"
            )
        if 'foreign key constraint' in str(e):
            raise HTTPException(status_code=400, detail="Base model not found")
        logger.error(
            f"IntegrityError:{e}\n StackTrace:\n {traceback.format_exc()}")
        raise HTTPException(status_code=400,
                            detail="An integrity error occurred")

    return db_to_schema(db_adapter)


@router.put("/v1alpha1/model/{model_id}/adapters/{adapter_id}",
            response_model=ModelAdapterSchema)
def update_model_adapter(model_id: UUID,
                         adapter_id: UUID,
                         adapter: ModelAdapterSchema,
                         db: Session = Depends(get_db)):
    if adapter.base_model and model_id != adapter.base_model.id:
        raise HTTPException(
            status_code=400,
            detail=
            "Model ID in the adapter does not match the model ID in the path")
    if not adapter.path and not adapter.hf_id:
        raise HTTPException(status_code=400,
                            detail="Either path or hf_id must be specified")
    db_adapter = get_model_adapter(db, model_id, adapter_id)
    db_adapter.name = adapter.name
    db_adapter.model_id = model_id
    db_adapter.path = adapter.path
    db_adapter.hf_id = adapter.hf_id
    try:
        db.commit()
        db.refresh(db_adapter)
    except IntegrityError as e:
        db.rollback()
        if 'uq_model_adapter_name' in str(e):
            raise HTTPException(
                status_code=400,
                detail=
                "Model adapter with this name already exists for the given model"
            )
        if 'foreign key constraint' in str(e):
            raise HTTPException(status_code=400, detail="Base model not found")
        logger.error(
            f"IntegrityError:{e}\n StackTrace:\n {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid request")

    return db_to_schema(db_adapter)


@router.delete("/v1alpha1/model/{model_id}/adapters/{adapter_id}",
               status_code=204)
def delete_model_adapter(model_id: UUID,
                         adapter_id: UUID,
                         db: Session = Depends(get_db)):
    db_adapter = get_model_adapter(db, model_id, adapter_id)
    db.delete(db_adapter)
    db.commit()
