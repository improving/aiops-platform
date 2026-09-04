import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from utils import genid


class NotebookInstanceSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    name: str
    namespace: str | None = "ai-stack"
    type: str
    framework: str | None = None
    nvidia_gpu: bool
    image: str | None = None
    resources_cpu: str | None = None
    resources_memory: str | None = None
    resources_gpu: str | None = None
    storage_size: str | None = None
    service_type: str | None = None
    service_port: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status: str | None = None
    ready: bool | None = False
    endpoint: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in ["jupyter", "vscode", "rstudio"]:
            raise ValueError("Invalid type")
        return v

    @field_validator("framework")
    @classmethod
    def validate_framework(cls, v, values):
        if "type" in values.data:
            if values.data["type"] == "jupyter" and v not in [
                "pytorch",
                "tensorflow",
            ]:
                raise ValueError("Invalid framework for type jupyter")
            if values.data["type"] == "vscode" and v not in [
                "python",
                "",
                None,
            ]:
                raise ValueError("Invalid framework for type vscode")
        return v

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    model_config = ConfigDict(from_attributes=True)
