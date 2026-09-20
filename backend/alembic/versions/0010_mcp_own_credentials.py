"""MCP servers where each member brings their own credential: the header
shape the members' values go into, and where to get one.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-19 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("user_auth_type", "user_auth_header", "credential_help_url")


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)
