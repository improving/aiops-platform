import uuid

from pydantic import BaseModel, ConfigDict


class EngineDefaultConfigEnvVars(BaseModel):
    name: str | None = None
    chart_type: str | None = None
    defaultValue: str | None = None
    editable: bool | None = False

    model_config = ConfigDict(from_attributes=True)


class EngineDefaultConfigArgs(BaseModel):
    name: str | None = None
    chart_type: str | None = None
    defaultValue: str | None = None
    editable: bool | None = False

    model_config = ConfigDict(from_attributes=True)


class EngineSchema(BaseModel):
    id: uuid.UUID
    name: str | None = None
    llm_support: bool | None = False
    embedding_support: bool | None = False
    reranking_support: bool | None = False
    prompt_guard_support: bool | None = False
    vector_db_support: bool | None = False
    cpu: bool | None = False
    default_config: list[EngineDefaultConfigEnvVars] | None = None
    default_args: list[EngineDefaultConfigArgs] | None = None

    model_config = ConfigDict(from_attributes=True)
