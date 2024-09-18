import uuid
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

from schemas.vectordb import VectorDBSchema

class VectorDBInstanceSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    vectorDB: VectorDBSchema
    configParams: Optional[Dict[str, Any]] = None
    endpoint: Optional[str] = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"exclude": ["vectorDB"]}
    }
