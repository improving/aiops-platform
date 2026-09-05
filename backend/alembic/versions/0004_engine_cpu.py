"""Engines: the ``cpu`` flag for engines that run without a GPU.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("engines") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cpu",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("engines") as batch_op:
        batch_op.drop_column("cpu")
