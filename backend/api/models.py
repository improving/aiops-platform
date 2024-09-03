from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from .db import get_db_connection

router = APIRouter()

# Pydantic model
class Model(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: Optional[str] = ""
    modelId: Optional[str] = ""
    description: Optional[str] = ""
    category: Optional[str] = ""
    subcategory: Optional[str] = ""
    size: Optional[int] = 0


# API to get model information
@router.get("/v1alpha1/models", response_model=List[Model])
def get_models():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, modelId, description, category, subcategory, size FROM models")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="No models found")
    return [dict(row) for row in rows]