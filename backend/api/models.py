import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.models import DBModel
from schemas.model import ModelSchema

router = APIRouter()


# API to get model information
@router.get("/v1alpha1/models", response_model=List[ModelSchema])
def get_models(db: Session = Depends(get_db)):
    models = db.query(DBModel).all()
    if not models:
        raise HTTPException(status_code=404, detail="No models found")
    for model in models:
        model.countAdapters = len(model.model_adapters)
    return models


@router.get("/v1alpha1/models/{id}", response_model=ModelSchema)
def get_model(id: uuid.UUID, db: Session = Depends(get_db)):
    model = db.query(DBModel).filter(DBModel.id == id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model.countAdapters = len(model.model_adapters)
    return model
