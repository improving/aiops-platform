from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from .db import get_db_connection

router = APIRouter()

# Pydantic model
class Engine(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: Optional[str] = ""
    description: Optional[str] = ""
    helm_chart_repo: Optional[str] = ""


# API to get engine information
@router.get("/v1alpha1/engines", response_model=List[Engine])
def get_engines():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, helm_chart_repo FROM engines")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="No engines found")
    return [dict(row) for row in rows]