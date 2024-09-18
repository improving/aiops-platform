import json
from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session, relationship
from sqlalchemy import JSON, UUID, Column, ForeignKey, String

from api.database import Base, get_db
from logger import setup_logger
from schemas.vectordb_instance import VectorDBInstanceSchema

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)

# SQLAlchemy model
class DBVectorDBInstance(Base):
    __tablename__ = "vectordb_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vectordb_id = Column(UUID(as_uuid=True), ForeignKey('vectordb.id'))
    configParams = Column(JSON, nullable=True)  # Change this line
    endpoint = Column(String, nullable=True)

    vectorDB = relationship("DBVectorDB")

@router.get("/v1alpha1/vectordb_instances", response_model=List[VectorDBInstanceSchema])
def get_vectordb_instances(db: Session = Depends(get_db)):
    vectordb_instances = db.query(DBVectorDBInstance).all()
    return vectordb_instances  # SQLAlchemy will handle the conversion

@router.get("/v1alpha1/vectordb_instances/{id}", response_model=VectorDBInstanceSchema)
def get_vectordb_instance(id: uuid.UUID = Path(
        description="The ID of the vector database instance to retrieve"),
        db: Session = Depends(get_db)):
    vectordb_instance = db.query(DBVectorDBInstance).filter(DBVectorDBInstance.id == id).first()
    if not vectordb_instance:
        raise HTTPException(status_code=404, detail="Vector database instance not found")

    return vectordb_instance

@router.post("/v1alpha1/vectordb_instances", response_model=VectorDBInstanceSchema, status_code=201)
def create_vectordb_instance(vectordb_instance: VectorDBInstanceSchema, db: Session = Depends(get_db)):
    vectorDBInstance = DBVectorDBInstance(
        vectordb_id=vectordb_instance.vectorDB.id,
        configParams=vectordb_instance.configParams,  # No need for json.dumps()
        endpoint=vectordb_instance.endpoint
    )
    db.add(vectorDBInstance)
    db.commit()
    db.refresh(vectorDBInstance)
    return vectorDBInstance  # SQLAlchemy will handle the conversion

@router.put("/v1alpha1/vectordb_instances/{id}", response_model=VectorDBInstanceSchema)
def update_vectordb_instance(vectordb_instance: VectorDBInstanceSchema, id: uuid.UUID = Path(
        description="The ID of the vector database instance to update"),
        db: Session = Depends(get_db)):
    db_vectordb_instance = db.query(DBVectorDBInstance).filter(DBVectorDBInstance.id == id).first()
    if not db_vectordb_instance:
        raise HTTPException(status_code=404, detail="Vector database instance not found")
    db_vectordb_instance.vectordb_id = vectordb_instance.vectorDB.id
    db_vectordb_instance.configParams = vectordb_instance.configParams
    db_vectordb_instance.endpoint = vectordb_instance.endpoint
    db.commit()
    db.refresh(db_vectordb_instance)

    return db_vectordb_instance

@router.delete("/v1alpha1/vectordb_instances/{id}", status_code=204)
def delete_vectordb_instance(id: uuid.UUID = Path(
        description="The ID of the vector database instance to delete"),
        db: Session = Depends(get_db)):
    db_vectordb_instance = db.query(DBVectorDBInstance).filter(DBVectorDBInstance.id == id).first()
    if not db_vectordb_instance:
        raise HTTPException(status_code=404, detail="Vector database instance not found")
    db.delete(db_vectordb_instance)
    db.commit()
    return {"message": "Vector database instance deleted successfully"}
