"""MCP servers: one row per server an organization registered, and one
row per credential of it (the organization's shared one today, a
member's own later), each pointing at a Secret.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-19 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("transport", sa.String(), nullable=False),
        sa.Column("credential_mode", sa.String(), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("litellm_server_id", sa.String(), nullable=True),
        sa.Column("tools_cache", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_mcp_servers_org_id"
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_mcp_servers_org_name"),
    )
    op.create_table(
        "mcp_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("secret_name", sa.String(), nullable=False),
        sa.Column("auth_type", sa.String(), nullable=False),
        sa.Column("auth_header", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_servers.id"],
            name="fk_mcp_credentials_server_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mcp_credentials_user_id"
        ),
    )
    # NULLs are distinct in a unique constraint, so "one shared
    # credential per server" needs a partial index of its own.
    op.create_index(
        "uq_mcp_credentials_shared",
        "mcp_credentials",
        ["server_id"],
        unique=True,
        sqlite_where=sa.text("user_id IS NULL"),
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "uq_mcp_credentials_user",
        "mcp_credentials",
        ["server_id", "user_id"],
        unique=True,
        sqlite_where=sa.text("user_id IS NOT NULL"),
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_mcp_credentials_user", table_name="mcp_credentials")
    op.drop_index("uq_mcp_credentials_shared", table_name="mcp_credentials")
    op.drop_table("mcp_credentials")
    op.drop_table("mcp_servers")
