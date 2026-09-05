import uuid
from typing import Any

from pydantic import BaseModel, Field

from schemas.vectordb import VectorDBSchema
from utils import genid


class VectorDBInstanceSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    vectorDB: VectorDBSchema
    configParams: dict[str, Any] | None = None
    endpoint: str | None = None
    # The SDK endpoint behind the gateway, API-key protected (see
    # models/vectordb_instance.py).
    api_endpoint: str | None = None
    ready: bool | None = False
    status: str | None = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"exclude": ["vectorDB"]},
    }
