from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class McpServer(Base):
    """One MCP server an organization admin registered
    (``api/mcp.py``). ``source`` is ``remote`` (a URL) today; a server
    the platform deploys is a later value, and nothing that reads the
    registry depends on which. The credential is never in this row: see
    ``McpCredential``.
    """

    __tablename__ = "mcp_servers"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    # Who can see and use the server (``utils/mcp_scope.py``):
    # organization = org_id set, owner_id NULL (every member);
    # personal     = org_id and owner_id set (the owner, in that org);
    # platform     = org_id NULL (every organization).
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # A slug, [a-z0-9_]: with the organization it makes the LiteLLM
    # alias, which prefixes every tool name the model sees.
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    source = Column(String, nullable=False, default="remote")
    url = Column(String, nullable=False)
    transport = Column(String, nullable=False, default="http")
    # none | shared (one organization credential) | per_user (each
    # member brings their own, in the header shape the two columns
    # below give; a member supplies only the value).
    credential_mode = Column(String, nullable=False, default="none")
    user_auth_type = Column(String, nullable=True)
    user_auth_header = Column(String, nullable=True)
    # Where a member gets a credential ("Create a token on GitHub").
    credential_help_url = Column(String, nullable=True)
    # user_auth_type "oauth": each member signs in. What discovery and
    # client registration found (``utils/mcp_oauth.py``): issuer,
    # authorization_endpoint, token_endpoint, client_id, scopes,
    # token_auth ("none" | "client_secret_post" | "client_secret_basic").
    # A client secret is in a Secret, never here.
    oauth = Column(JSON, nullable=True)
    # Tool names the organization allows; NULL allows all, new ones too.
    allowed_tools = Column(JSON, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    # When the chat playground asks the member before a tool of this
    # server runs: never | writes (every tool that does not say it only
    # reads) | always. The admin's floor; a member can ask for more.
    approval = Column(String, nullable=False, default="never")
    litellm_server_id = Column(String, nullable=True)
    # [{name, description, read_only}] from the last successful refresh.
    tools_cache = Column(JSON, nullable=True)
    # connected | unreachable, from create and refresh; never polled.
    status = Column(String, nullable=False, default="connected")
    checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    credentials = relationship(
        "McpCredential",
        back_populates="server",
        cascade="all, delete-orphan",
    )

    # One name for each place a server is shared in (NULLs are distinct
    # in a plain constraint, and a member's personal server must not
    # block the name for the organization): see ``api.mcp._name_taken``.
    __table_args__ = (
        Index(
            "uq_mcp_servers_org_name",
            "org_id",
            "name",
            unique=True,
            sqlite_where=text("org_id IS NOT NULL AND owner_id IS NULL"),
            postgresql_where=text("org_id IS NOT NULL AND owner_id IS NULL"),
        ),
        Index(
            "uq_mcp_servers_owner_name",
            "org_id",
            "owner_id",
            "name",
            unique=True,
            sqlite_where=text("owner_id IS NOT NULL"),
            postgresql_where=text("owner_id IS NOT NULL"),
        ),
        Index(
            "uq_mcp_servers_platform_name",
            "name",
            unique=True,
            sqlite_where=text("org_id IS NULL"),
            postgresql_where=text("org_id IS NULL"),
        ),
    )


class McpCredential(Base):
    """Where one credential of an MCP server lives: the Secret's name
    and the header it goes into, never the value. ``user_id`` NULL is
    the organization's shared credential; a row with a user is that
    member's own (a later mode). A table of its own, so a new kind of
    credential is a new row and not a new column on the server.
    """

    __tablename__ = "mcp_credentials"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    server_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    secret_name = Column(String, nullable=False)
    # bearer (Authorization: Bearer <value>) | header (<auth_header>: <value>)
    auth_type = Column(String, nullable=False, default="bearer")
    auth_header = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    server = relationship("McpServer", back_populates="credentials")

    # Two partial indexes: NULLs are distinct in a plain unique
    # constraint, which would allow a second shared credential.
    __table_args__ = (
        Index(
            "uq_mcp_credentials_shared",
            "server_id",
            unique=True,
            sqlite_where=text("user_id IS NULL"),
            postgresql_where=text("user_id IS NULL"),
        ),
        Index(
            "uq_mcp_credentials_user",
            "server_id",
            "user_id",
            unique=True,
            sqlite_where=text("user_id IS NOT NULL"),
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )


class McpOAuthState(Base):
    """One started sign-in: the ``state`` the authorization server
    sends back (stored as a hash), bound to the member and the server
    that started it, with the PKCE verifier. Single use, ten minutes."""

    __tablename__ = "mcp_oauth_states"

    state_hash = Column(String, primary_key=True)
    server_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    code_verifier = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
