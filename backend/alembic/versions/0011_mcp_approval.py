"""MCP servers: when the chat playground asks the member before a tool of
the server runs (never, writes, always).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-20 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(
            sa.Column(
                "approval",
                sa.String(),
                nullable=False,
                server_default="never",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("approval")
