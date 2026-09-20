"""MCP servers where each member signs in with OAuth: what discovery
found, on the server row, and the started sign-ins.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-20 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(sa.Column("oauth", sa.JSON(), nullable=True))
    op.create_table(
        "mcp_oauth_states",
        sa.Column("state_hash", sa.String(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_verifier", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("state_hash"),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_servers.id"],
            name="fk_mcp_oauth_states_server_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mcp_oauth_states_user_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_states")
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("oauth")
