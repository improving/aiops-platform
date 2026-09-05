"""LiteLLM bookkeeping: the registered model per instance, the team and
key per organization, and an optional budget.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-05 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("inference_instances") as batch_op:
        batch_op.add_column(
            sa.Column("litellm_model_name", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("litellm_model_id", sa.String(), nullable=True)
        )
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(
            sa.Column("litellm_team_id", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("litellm_key_secret_name", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("budget_usd", sa.Numeric(12, 2), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("budget_usd")
        batch_op.drop_column("litellm_key_secret_name")
        batch_op.drop_column("litellm_team_id")
    with op.batch_alter_table("inference_instances") as batch_op:
        batch_op.drop_column("litellm_model_id")
        batch_op.drop_column("litellm_model_name")
