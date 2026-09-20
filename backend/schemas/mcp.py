import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from schemas.mcp_deploy import McpDeploySchema


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
    # Characters of the whole definition (name, description, input
    # schema); None for a tool listed before this was kept.
    size: int | None = None


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
    # per_user by sign-in (OAuth) and not by a pasted value.
    oauth: bool = False
    # The host a member signs in at, so the dialog can say it first.
    sign_in_host: str | None = None
    allowed_tools: list[str] | None = None
    # never | writes | always: when Chat asks before a tool runs.
    approval: str = "never"
    enabled: bool
    status: str
    checked_at: datetime | None = None
    tools: list[McpToolSchema] = []
    # The prefix of this server's tool names as a model sees them.
    tool_prefix: str
    # organization | personal | platform, and whether the caller may
    # change the server (an admin, its owner, a platform admin).
    scope: str = "organization"
    can_change: bool = False
    # The workload of a server the platform deployed; None for a remote
    # one. ``deploy.usable`` says whether it takes requests.
    deploy: McpDeploySchema | None = None


class McpCredentialInput(BaseModel):
    auth_type: str = "bearer"
    auth_header: str | None = None
    value: str = Field(min_length=1)


class McpOAuthInput(BaseModel):
    """Each member signs in (OAuth). Empty is enough when the server's
    authorization server registers clients by itself; else the client
    of an OAuth application made there, with the platform's redirect
    URI."""

    client_id: str | None = None
    client_secret: str | None = None
    scopes: list[str] | None = None
    # Hosts, other than the issuer's, that may carry the authorization
    # or the token endpoint (an issuer on accounts.example.com with a
    # token endpoint on oauth2.example.com).
    allow_hosts: list[str] | None = None


class McpOAuthCallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)
    # RFC 9207, when the authorization server sent it.
    iss: str | None = None


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
    # Each member signs in with OAuth (then ``credential`` is not used).
    oauth: McpOAuthInput | None = None
    # organization (an admin), personal (any writer, for themselves) or
    # platform (a platform admin, for every organization).
    scope: str = "organization"

    _help_url = field_validator("credential_help_url")(_web_url)
    _approval = field_validator("approval")(_approval_mode)

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        if value not in ("organization", "personal", "platform"):
            raise ValueError(
                "scope must be one of organization, personal, platform"
            )
        return value


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
