"""One MCP server name for each place a server is shared in: the
organization, one member, the platform. The plain constraint on
(org_id, name) let two platform servers share a name (NULLs are
distinct) and let a member's personal server block the name for the
organization.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-20 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHARED = "org_id IS NOT NULL AND owner_id IS NULL"
OWNED = "owner_id IS NOT NULL"
PLATFORM = "org_id IS NULL"


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint("uq_mcp_servers_org_name", type_="unique")
    op.create_index(
        "uq_mcp_servers_org_name",
        "mcp_servers",
        ["org_id", "name"],
        unique=True,
        sqlite_where=sa.text(SHARED),
        postgresql_where=sa.text(SHARED),
    )
    op.create_index(
        "uq_mcp_servers_owner_name",
        "mcp_servers",
        ["org_id", "owner_id", "name"],
        unique=True,
        sqlite_where=sa.text(OWNED),
        postgresql_where=sa.text(OWNED),
    )
    op.create_index(
        "uq_mcp_servers_platform_name",
        "mcp_servers",
        ["name"],
        unique=True,
        sqlite_where=sa.text(PLATFORM),
        postgresql_where=sa.text(PLATFORM),
    )


def downgrade() -> None:
    op.drop_index("uq_mcp_servers_platform_name", table_name="mcp_servers")
    op.drop_index("uq_mcp_servers_owner_name", table_name="mcp_servers")
    op.drop_index("uq_mcp_servers_org_name", table_name="mcp_servers")
    with op.batch_alter_table("mcp_servers") as batch:
        batch.create_unique_constraint(
            "uq_mcp_servers_org_name", ["org_id", "name"]
        )
