"""MCP servers of one member (owner_id) and of the whole platform
(org_id NULL), next to an organization's.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-20 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.alter_column("org_id", existing_type=sa.UUID(), nullable=True)
        batch.add_column(sa.Column("owner_id", sa.UUID(), nullable=True))
        batch.create_foreign_key(
            "fk_mcp_servers_owner_id", "users", ["owner_id"], ["id"]
        )


def downgrade() -> None:
    # Personal and platform servers have no place in the older schema.
    op.execute(
        "DELETE FROM mcp_servers WHERE owner_id IS NOT NULL OR org_id IS NULL"
    )
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint("fk_mcp_servers_owner_id", type_="foreignkey")
        batch.drop_column("owner_id")
        batch.alter_column("org_id", existing_type=sa.UUID(), nullable=False)
