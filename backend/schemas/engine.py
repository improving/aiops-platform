import uuid
from typing import Optional

from pydantic import BaseModel


class EngineSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    llm_support: Optional[bool] = None
    embedding_support: Optional[bool] = None
    reranking_support: Optional[bool] = None

    class Config:
        from_attributes = True
