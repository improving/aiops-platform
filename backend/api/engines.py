import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Boolean, Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from schemas.engine import EngineSchema

from .database import Base, get_db

router = APIRouter()


# SQLAlchemy model
class DBEngine(Base):
    __tablename__ = "engines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    llm_support = Column(Boolean, nullable=False)
    embedding_support = Column(Boolean, nullable=False)
    reranking_support = Column(Boolean, nullable=False)


# API to get engine information
@router.get("/v1alpha1/engines", response_model=List[EngineSchema])
def get_engines(db: Session = Depends(get_db)):
    engines = db.query(DBEngine).all()
    if not engines:
        raise HTTPException(status_code=404, detail="No engines found")
    return engines
