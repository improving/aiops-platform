import uuid

from pydantic import BaseModel, ConfigDict


class ProviderModelSchema(BaseModel):
    id: uuid.UUID
    model: str
    display_name: str
    litellm_model_name: str
    capability: str
    context_length: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


class ProviderSchema(BaseModel):
    """The response shape of a provider row. There is no ``api_key``
    field: the key is never echoed back, only ``has_key``."""

    id: uuid.UUID
    kind: str
    name: str
    base_url: str | None = None
    enabled: bool = True
    has_key: bool = True
    models: list[ProviderModelSchema] = []

    model_config = ConfigDict(from_attributes=True)


class DiscoveredModelSchema(BaseModel):
    id: str
    display_name: str
    context_length: int | None = None
    capability: str
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None


class ProviderDiscoverRequest(BaseModel):
    kind: str
    api_key: str
    base_url: str | None = None


class ProviderCreateRequest(BaseModel):
    kind: str
    name: str
    base_url: str | None = None
    api_key: str
    models: list[str] = []
    # Optional labels from discovery, keyed by model id.
    display_names: dict[str, str] = {}


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    api_key: str | None = None


class ProviderModelsAddRequest(BaseModel):
    models: list[str]
    display_names: dict[str, str] = {}
