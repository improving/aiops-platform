"""Hosted providers: one row per organization provider (OpenAI,
Anthropic, Gemini, Groq, OpenRouter) and one row per model exposed from
it, with its LiteLLM registration.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("secret_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_providers_org_id"
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_providers_org_name"),
    )
    op.create_table(
        "provider_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("litellm_model_name", sa.String(), nullable=False),
        sa.Column("litellm_model_id", sa.String(), nullable=True),
        sa.Column("capability", sa.String(), nullable=False),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("input_cost_per_token", sa.Numeric(18, 10), nullable=True),
        sa.Column("output_cost_per_token", sa.Numeric(18, 10), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name="fk_provider_models_provider_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "model",
            name="uq_provider_models_provider_model",
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_models")
    op.drop_table("providers")
