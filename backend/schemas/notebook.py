import re
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

# The kf-notebooks chart names the Service and the Notebook resource
# "<release>-kf-notebooks-<name>" and truncates that at 41 characters,
# with release = "<name>-<8 id chars>". So the length is 2n + 23, and it
# stays under 41 (no truncation, no name collisions) only when n <= 9.
NOTEBOOK_NAME_MAX_LENGTH = 9
# DNS-1123 label, which Kubernetes requires for Service and Notebook names.
NOTEBOOK_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


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


class NotebookCreateSchema(NotebookInstanceSchema):
    """Request body for creating a notebook.

    The name rules live here and not on NotebookInstanceSchema, because that
    schema is also the response model and rows created before the rules
    existed must still serialize.
    """

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        too_long = len(v) > NOTEBOOK_NAME_MAX_LENGTH
        if too_long or not NOTEBOOK_NAME_PATTERN.match(v):
            raise ValueError(
                "must be lowercase letters, digits and '-', start and end "
                f"with a letter or digit, and be at most "
                f"{NOTEBOOK_NAME_MAX_LENGTH} characters long, because the "
                "chart builds '<name>-<id>-kf-notebooks-<name>' and cuts it "
                "at 41 characters"
            )
        return v
