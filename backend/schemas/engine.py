import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EngineDefaultConfigEnvVars(BaseModel):
    name: Optional[str] = None
    chart_type: Optional[str] = None
    defaultValue: Optional[str] = None
    editable: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)


class EngineDefaultConfigArgs(BaseModel):
    name: Optional[str] = None
    chart_type: Optional[str] = None
    defaultValue: Optional[str] = None
    editable: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)


class EngineSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    llm_support: Optional[bool] = False
    embedding_support: Optional[bool] = False
    reranking_support: Optional[bool] = False
    prompt_guard_support: Optional[bool] = False
    vector_db_support: Optional[bool] = False
    default_config: Optional[list[EngineDefaultConfigEnvVars]] = None
    default_args: Optional[list[EngineDefaultConfigArgs]] = None

    model_config = ConfigDict(from_attributes=True)
