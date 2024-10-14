import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from schemas.vectordb import VectorDBSchema
from utils import genid


class VectorDBInstanceSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=genid.uuid4_gen())
    vectorDB: VectorDBSchema
    configParams: Optional[Dict[str, Any]] = None
    endpoint: Optional[str] = None
    ready: Optional[bool] = False
    status: Optional[str] = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "exclude": ["vectorDB"]
        }
    }
