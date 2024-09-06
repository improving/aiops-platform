from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session
from .database import Base, get_db
from schemas.engine import EngineSchema

router = APIRouter()

# SQLAlchemy model
class DBEngine(Base):
    __tablename__ = "engines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String)
    helm_chart_repo = Column(String, nullable=False)
    helm_chart_name = Column(String, nullable=False)

# API to get engine information
@router.get("/v1alpha1/engines", response_model=List[EngineSchema])
def get_engines(db: Session = Depends(get_db)):
    engines = db.query(DBEngine).all()
    if not engines:
        raise HTTPException(status_code=404, detail="No engines found")
    return engines