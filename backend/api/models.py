import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Column, Integer, String
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
    size = Column(Integer)


# API to get model information
@router.get("/v1alpha1/models", response_model=List[ModelSchema])
def get_models(db: Session = Depends(get_db)):
    models = db.query(DBModel).all()
    if not models:
        raise HTTPException(status_code=404, detail="No models found")
    return models
