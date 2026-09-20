"""Deployed MCP servers: the catalog, an instance, and the ``deploy``
block a deployed server carries in the list of servers."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from schemas.launch import LaunchProgressSchema


class McpSettingSchema(BaseModel):
    name: str
    label: str
    help: str = ""
    secret: bool = False
    required: bool = False
    # A switch that adds this argument, not an environment variable.
    flag: str | None = None
    default: str | None = None


class McpCatalogEntrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    title: str
    description: str | None = None
    docs_url: str | None = None
    image: str
    tag: str
    port: int
    path: str
    settings: list[McpSettingSchema]
    egress: str
    source: str
    source_id: str
    source_version: str | None = None
    status: str
    synced_at: datetime | None = None


class McpCatalogReviewSchema(McpCatalogEntrySchema):
    """What a platform admin reads before Publish: also how the image
    starts, and what the importer changed."""

    command: list[str]
    args: list[str]
    notes: list[str]
    in_use: int = 0


class McpCatalogImportRequest(BaseModel):
    # The registry's name of the entry (``io.github.acme/server``).
    name: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=100)
    # The catalog name; by default derived from ``name``.
    slug: str | None = None


class McpCatalogUpdateRequest(BaseModel):
    name: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    args: list[str] | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    path: str | None = None
    settings: list[McpSettingSchema] | None = None
    egress: str | None = None
    status: str | None = None


class McpDeployRequest(BaseModel):
    # The catalog entry's name.
    catalog: str
    name: str
    description: str | None = Field(default=None, max_length=1000)
    settings: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] | None = None
    approval: str | None = None


class McpInstanceSettingsRequest(BaseModel):
    # A secret setting that is left out keeps its value.
    settings: dict[str, str] = Field(default_factory=dict)


class McpDeploySchema(BaseModel):
    """The workload side of a deployed server, in the list of servers."""

    instance_id: uuid.UUID
    catalog: str
    catalog_title: str
    image: str
    tag: str
    status: str | None = None
    ready: bool = False
    launch: LaunchProgressSchema | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    # Ready, registered in the proxy, and connected: it takes requests.
    usable: bool = False
    # The catalog entry has moved to another image since the install.
    upgrade_available: bool = False


class McpInstanceSchema(McpDeploySchema):
    server_id: uuid.UUID
    name: str
    # The plain values, and which secret settings have a value.
    settings: dict[str, str]
    secret_settings: list[str]
    schema_: list[McpSettingSchema] = Field(alias="schema")

    model_config = ConfigDict(populate_by_name=True)
