from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.vectordb import DBVectorDB
from schemas.vectordb import VectorDBSchema

router = APIRouter()


# API to get vectordb catalog
@router.get("/v1alpha1/vectordb", response_model=List[VectorDBSchema])
def get_vectordb(db: Session = Depends(get_db)):
    """
    Retrieve all vector databases from the database.

    Returns:
        List[VectorDBSchema]: A list of all vector databases.

    Raises:
        HTTPException: If no vector databases are found in the database.
    """
    vectordb = db.query(DBVectorDB).all()
    if not vectordb:
        raise HTTPException(status_code=404,
                            detail="No vector databases found")
    return vectordb
