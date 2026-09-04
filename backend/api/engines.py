from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.engines import DBEngine
from schemas.engine import EngineSchema

router = APIRouter()


# API to get engine information
@router.get("/v1alpha1/engines", response_model=list[EngineSchema])
def get_engines(db: Session = Depends(get_db)):
    """
    Retrieve all engines from the database.

    Returns:
        List[EngineSchema]: A list of all engines.

    Raises:
        HTTPException: If no engines are found in the database.
    """
    engines = db.query(DBEngine).all()
    if not engines:
        raise HTTPException(status_code=404, detail="No engines found")
    return engines
