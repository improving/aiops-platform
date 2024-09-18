import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from schemas.vectordb import VectorDBSchema

from .database import Base, get_db

router = APIRouter()

# SQLAlchemy model
class DBVectorDB(Base):
    __tablename__ = "vectordb"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    chart_repo = Column(String, nullable=False)
    chart_name = Column(String, nullable=False)

# API to get vectordb catalog
@router.get("/v1alpha1/vectordb", response_model=List[VectorDBSchema])
def get_vectordb(db: Session = Depends(get_db)):
    vectordb = db.query(DBVectorDB).all()
    if not vectordb:
        raise HTTPException(status_code=404, detail="No vector databases found")
    return vectordb
