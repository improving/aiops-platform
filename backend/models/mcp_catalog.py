import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base

SOURCE_BUILTIN = "builtin"
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_DEPRECATED = "deprecated"
CATALOG_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED, STATUS_DEPRECATED)

EGRESS_NONE = "none"
EGRESS_PUBLIC = "public"
EGRESS_CLUSTER = "cluster"
EGRESS_MODES = (EGRESS_NONE, EGRESS_PUBLIC, EGRESS_CLUSTER)

_NAMESPACE = uuid.UUID("6a1c7c0e-1f4b-4c58-9d55-5d2f6d1b0c15")


def builtin_id(name: str) -> uuid.UUID:
    """The id of a seeded entry, from its name. Not from ``genid``: a
    seed row must not move the deterministic ids of ``TEST_MODE``, which
    the snapshots hold."""
    return uuid.uuid5(_NAMESPACE, f"mcp-catalog:{name}")


class McpCatalogEntry(Base):
    """An MCP server the platform can deploy: an image that speaks
    streamable HTTP, how to start it, and the settings an admin fills.
    Global, like the other catalogs.

    ``source`` is ``builtin`` (the seed, ``raw_data/mcp_catalog.yaml``)
    or ``mcp-registry`` (imported by a platform admin). Only a
    ``published`` entry can be deployed, and only a platform admin sees
    a ``draft``: a draft is an image that nobody has read yet.
    """

    __tablename__ = "mcp_catalog"

    id = Column(UUID(as_uuid=True), primary_key=True)
    # The slug a deploy names, and the default of the server's name.
    name = Column(String, nullable=False, unique=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    docs_url = Column(String, nullable=True)
    image = Column(String, nullable=False)
    # A tag, or "@sha256:..."; never "latest".
    tag = Column(String, nullable=False)
    command = Column(JSON, nullable=False, default=list)
    # May hold the placeholders {host}, {port} and {path}.
    args = Column(JSON, nullable=False, default=list)
    port = Column(Integer, nullable=False)
    path = Column(String, nullable=False, default="/mcp")
    # [{name, label, help, secret, required, default}]: the environment
    # variables an admin fills; nothing else reaches the pod.
    settings = Column(JSON, nullable=False, default=list)
    egress = Column(String, nullable=False, default=EGRESS_PUBLIC)
    chart_repo = Column(String, nullable=False)
    chart_name = Column(String, nullable=False)
    source = Column(String, nullable=False, default=SOURCE_BUILTIN)
    source_id = Column(String, nullable=False)
    source_version = Column(String, nullable=True)
    status = Column(String, nullable=False, default=STATUS_DRAFT)
    # What the importer changed or could not take over, for the review.
    notes = Column(JSON, nullable=False, default=list)
    synced_at = Column(DateTime, nullable=True)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_mcp_catalog_source"),
    )
