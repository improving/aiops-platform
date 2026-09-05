import uuid

from pydantic import BaseModel, ConfigDict


class ServingOptionSchema(BaseModel):
    id: uuid.UUID
    engine: str
    reference: str
    default_args: dict | None = None
    # Populated only by GET /v1alpha1/models/{id}/serving-options (a left
    # join with the engine rows): None for a hosted option such as
    # "openrouter", which has no engines row and no chart to launch; the
    # wizard renders only options with an engine_id.
    engine_id: uuid.UUID | None = None
    cpu: bool | None = None

    model_config = ConfigDict(from_attributes=True)
