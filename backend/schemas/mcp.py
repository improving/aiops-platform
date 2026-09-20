import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _web_url(value: str | None) -> str | None:
    """A link a member follows next to the field where they type a
    personal token: a web address and nothing else."""
    if value is None or value == "":
        return value
    if not value.lower().startswith(("https://", "http://")):
        raise ValueError("credential_help_url must be an http(s) URL")
    return value


APPROVAL_MODES = ("never", "writes", "always")


def _approval_mode(value: str | None) -> str | None:
    if value is not None and value not in APPROVAL_MODES:
        raise ValueError(
            f"approval must be one of {', '.join(APPROVAL_MODES)}"
        )
    return value


class McpToolSchema(BaseModel):
    name: str
    description: str = ""
    # The MCP readOnlyHint; null when the server sends no annotations.
    read_only: bool | None = None


class McpServerSchema(BaseModel):
    """One MCP server as the API shows it. A credential is never
    echoed: ``credential_mode`` says which kind the server uses,
    ``my_credential`` what the caller must do about it (``not_needed``,
    ``set`` or ``missing``), and ``credential_set_at`` is for admins."""

    id: uuid.UUID
    name: str
    description: str | None = None
    source: str
    url: str
    transport: str
    credential_mode: str
    my_credential: str
    credential_set_at: datetime | None = None
    # per_user servers: the header a member's value goes into
    # ("Authorization" for a bearer), and where to get a value.
    credential_header: str | None = None
    credential_help_url: str | None = None
    allowed_tools: list[str] | None = None
    # never | writes | always: when Chat asks before a tool runs.
    approval: str = "never"
    enabled: bool
    status: str
    checked_at: datetime | None = None
    tools: list[McpToolSchema] = []
    # The prefix of this server's tool names as a model sees them.
    tool_prefix: str


class McpCredentialInput(BaseModel):
    auth_type: str = "bearer"
    auth_header: str | None = None
    value: str = Field(min_length=1)


class McpDiscoverRequest(BaseModel):
    url: str
    transport: str = "http"
    credential: McpCredentialInput | None = None


class McpServerCreateRequest(McpDiscoverRequest):
    """``credential_mode`` is ``shared`` (the default with a credential)
    or ``per_user``: then ``credential`` is the admin's own, used for
    the connection test and kept as theirs, and every other member
    brings their own value in the same header shape."""

    name: str
    description: str | None = None
    allowed_tools: list[str] | None = None
    credential_mode: str | None = None
    credential_help_url: str | None = None
    approval: str = "never"

    _help_url = field_validator("credential_help_url")(_web_url)
    _approval = field_validator("approval")(_approval_mode)


class McpOwnCredentialRequest(BaseModel):
    value: str = Field(min_length=1)


class McpServerUpdateRequest(BaseModel):
    """Every field is optional; ``credential`` replaces the shared
    credential, ``remove_credential`` deletes it."""

    description: str | None = None
    url: str | None = None
    transport: str | None = None
    credential: McpCredentialInput | None = None
    remove_credential: bool = False
    allowed_tools: list[str] | None = None
    # allowed_tools=None means "no change"; this says "allow all".
    allow_all_tools: bool = False
    enabled: bool | None = None
    # A change of mode needs ``credential``: the new shared one, or
    # (per_user) the admin's own, which also sets the header shape.
    credential_mode: str | None = None
    credential_help_url: str | None = None
    approval: str | None = None

    _help_url = field_validator("credential_help_url")(_web_url)
    _approval = field_validator("approval")(_approval_mode)
