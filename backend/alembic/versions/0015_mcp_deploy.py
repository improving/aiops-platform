"""MCP servers that the platform deploys: the catalog of images and the
instance (workload) rows, one for each deployed registry server.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-20 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_catalog",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("docs_url", sa.String(), nullable=True),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("egress", sa.String(), nullable=False),
        sa.Column("chart_repo", sa.String(), nullable=False),
        sa.Column("chart_name", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint(
            "source", "source_id", name="uq_mcp_catalog_source"
        ),
    )
    op.create_table(
        "mcp_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("catalog_id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("secret_settings", sa.JSON(), nullable=False),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.Column("startup", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("launch", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("registered_at", sa.DateTime(), nullable=True),
        sa.Column("ready_since", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id"),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_servers.id"],
            name="fk_mcp_instances_server_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"],
            ["mcp_catalog.id"],
            name="fk_mcp_instances_catalog_id",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_mcp_instances_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_mcp_instances_owner_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_instances")
    op.drop_table("mcp_catalog")
