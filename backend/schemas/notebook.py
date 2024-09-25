import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotebookInstance(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    name: str
    type: str
    framework: Optional[str] = None
    nvidia_gpu: bool
    image: Optional[str] = None
    resources_cpu: Optional[str] = None
    resources_memory: Optional[str] = None
    resources_gpu: Optional[str] = None
    storage_size: Optional[str] = None
    service_type: Optional[str] = None
    service_port: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    status: Optional[str] = None
    ready: Optional[bool] = False
    endpoint: Optional[str] = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if v not in ['jupyter', 'vscode', 'rstudio']:
            raise ValueError('Invalid type')
        return v

    @field_validator('framework')
    @classmethod
    def validate_framework(cls, v, values):
        if 'type' in values.data:
            if values.data['type'] == 'jupyter' and v not in [
                    'pytorch', 'tensorflow'
            ]:
                raise ValueError('Invalid framework for type jupyter')
            if values.data['type'] == 'vscode' and v not in ['python', '', None]:
                raise ValueError('Invalid framework for type vscode')
        return v

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={datetime: lambda v: v.isoformat()})
