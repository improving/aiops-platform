from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class McpInstance(Base):
    """The workload of a deployed MCP server: what a remote server has
    not. One instance, one registry row (``mcp_servers``,
    ``source = "deployed"``), and the instance goes when the server
    goes. ``status`` is the shared instance status
    (``utils/instance_status.py``); ``ready`` is what the poller's last
    tick saw, stored because nothing else reads a Running row again.
    """

    __tablename__ = "mcp_instances"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    server_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    catalog_id = Column(
        UUID(as_uuid=True), ForeignKey("mcp_catalog.id"), nullable=False
    )
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    # Who deployed it.
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # The plain settings; the secret ones are in Secret mcpi-<id8>-env,
    # and ``secret_settings`` names which of them are set.
    settings = Column(JSON, nullable=False, default=dict)
    secret_settings = Column(JSON, nullable=False, default=list)
    # What was installed: the catalog entry can move on. ``image`` and
    # ``tag`` with ``startup`` (command, args, port, path, egress and
    # the settings schema) are a copy made at deploy and at an explicit
    # image upgrade, never a live read of the entry: the proxy is
    # registered with this port and path, and an entry that a sync sent
    # back to draft must not change what a running server renders.
    image = Column(String, nullable=False)
    tag = Column(String, nullable=False)
    startup = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=True)
    ready = Column(Boolean, nullable=False, default=False)
    # What a pod that is not ready waits for, as the poller last saw it
    # (the other kinds derive it on each read; here the list of servers
    # is one query and asks no cluster).
    launch = Column(JSON, nullable=True)
    last_error = Column(String, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    # NULL until the proxy registration, the team permission and the
    # first discovery all succeeded: the poller's commit point.
    registered_at = Column(DateTime, nullable=True)
    # When the pod was first ready with no registration yet, for the
    # "the proxy cannot reach the pod" error after ten minutes.
    ready_since = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    server = relationship("McpServer", back_populates="instance")
    catalog = relationship("McpCatalogEntry")
