"""Workload credentials: the API-key bookkeeping per instance.

One row per (resource_kind, resource_id) records the names of the two
Kubernetes Secrets that hold the key (``utils/credentials.py``) and
when the value was shown to the owner. The key itself never enters the
database.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05 00:25:43.137530

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workload_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("resource_kind", sa.String(), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("secret_name", sa.String(), nullable=False),
        sa.Column("apikey_secret_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("shown_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_kind",
            "resource_id",
            name="uq_workload_credentials_resource",
        ),
    )


def downgrade() -> None:
    op.drop_table("workload_credentials")
