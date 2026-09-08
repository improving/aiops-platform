from pydantic import BaseModel


class LangflowModelSchema(BaseModel):
    """A name Langflow lists under the managed provider, with its label."""

    name: str
    label: str


class LangflowProvisionSchema(BaseModel):
    langflow_user: str
    organization: str
    models: list[LangflowModelSchema]
