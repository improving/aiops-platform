import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EngineSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    llm_support: Optional[bool] = False
    embedding_support: Optional[bool] = False
    reranking_support: Optional[bool] = False
    prompt_guard_support: Optional[bool] = False
    vector_db_support: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)
