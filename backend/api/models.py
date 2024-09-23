import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import BigInteger, Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from schemas.model import ModelSchema

from .database import Base, get_db

router = APIRouter()


# SQLAlchemy model
class DBModel(Base):
    __tablename__ = "models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    modelId = Column(String, nullable=False)
    description = Column(String)
    category = Column(String)
    subcategory = Column(String)
    size = Column(BigInteger)


# API to get model information
@router.get("/v1alpha1/models", response_model=List[ModelSchema])
def get_models(db: Session = Depends(get_db)):
    models = db.query(DBModel).all()
    if not models:
        raise HTTPException(status_code=404, detail="No models found")
    return models


@router.get("/v1alpha1/models/{id}", response_model=ModelSchema)
def get_model(id: uuid.UUID, db: Session = Depends(get_db)):
    model = db.query(DBModel).filter(DBModel.id == id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model
