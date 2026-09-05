"""Baseline: the schema the pre-Alembic code created with create_all.

Revision ID: 0001
Revises:
Create Date: 2026-09-04 23:34:47.489697

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "engine_charts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("chart_type", sa.String(), nullable=False),
        sa.Column("chart_repo", sa.String(), nullable=False),
        sa.Column("chart_name", sa.String(), nullable=False),
        sa.Column("chart_version", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("llm_support", sa.Boolean(), nullable=False),
        sa.Column("embedding_support", sa.Boolean(), nullable=False),
        sa.Column("reranking_support", sa.Boolean(), nullable=False),
        sa.Column("prompt_guard_support", sa.Boolean(), nullable=False),
        sa.Column("vector_db_support", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inference_instance_config_params",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("maxInputLength", sa.Integer(), nullable=True),
        sa.Column("maxTokens", sa.Integer(), nullable=True),
        sa.Column("maxBatchPrefillTokens", sa.Integer(), nullable=True),
        sa.Column("maxBatchTotalTokens", sa.Integer(), nullable=True),
        sa.Column("quantization", sa.String(), nullable=True),
        sa.Column("image", sa.String(), nullable=True),
        sa.Column("env_vars", sa.JSON(), nullable=True),
        sa.Column("args", sa.JSON(), nullable=True),
        sa.Column("enable_tracing", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table(
        "inference_instance_config_params", schema=None
    ) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_inference_instance_config_params_id"),
            ["id"],
            unique=False,
        )

    op.create_table(
        "models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("modelId", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notebooks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("framework", sa.String(), nullable=True),
        sa.Column("nvidia_gpu", sa.Boolean(), nullable=False),
        sa.Column("image", sa.String(), nullable=True),
        sa.Column("resources_cpu", sa.String(), nullable=True),
        sa.Column("resources_memory", sa.String(), nullable=True),
        sa.Column("resources_gpu", sa.String(), nullable=True),
        sa.Column("storage_size", sa.String(), nullable=True),
        sa.Column("service_type", sa.String(), nullable=True),
        sa.Column("service_port", sa.Integer(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vectordb",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("chart_repo", sa.String(), nullable=False),
        sa.Column("chart_name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engine_chart_dashboards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=True),
        sa.Column("dashboard_name", sa.String(), nullable=True),
        sa.Column("engine_id", sa.UUID(), nullable=True),
        sa.Column("engine_chart_id", sa.UUID(), nullable=True),
        sa.Column("panel_id", sa.String(), nullable=True),
        sa.Column("panel_name", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["engine_chart_id"],
            ["engine_charts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["engine_id"],
            ["engines.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engine_default_args",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("engine_id", sa.UUID(), nullable=False),
        sa.Column("chart_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("defaultValue", sa.String(), nullable=False),
        sa.Column("editable", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["engine_id"],
            ["engines.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engine_default_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("engine_id", sa.UUID(), nullable=False),
        sa.Column("chart_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("defaultValue", sa.String(), nullable=False),
        sa.Column("editable", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["engine_id"],
            ["engines.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "finetunes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inference_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=True),
        sa.Column("engine_id", sa.UUID(), nullable=True),
        sa.Column("host", sa.String(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.Column("healthEndpoint", sa.String(), nullable=True),
        sa.Column("metricsEndpoint", sa.String(), nullable=True),
        sa.Column("config_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["inference_instance_config_params.id"],
        ),
        sa.ForeignKeyConstraint(
            ["engine_id"],
            ["engines.id"],
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "model_adapters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(), nullable=True),
        sa.Column("hf_id", sa.String(), nullable=True),
        sa.CheckConstraint(
            "(path IS NOT NULL) OR (hf_id IS NOT NULL)",
            name="check_path_or_hf_id_not_null",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "name", name="uq_model_adapter_name"),
    )
    op.create_table(
        "vectordb_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("vectordb_id", sa.UUID(), nullable=True),
        sa.Column("configParams", sa.JSON(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["vectordb_id"],
            ["vectordb.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inference_instance_dashboards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("inference_instance_id", sa.UUID(), nullable=True),
        sa.Column("engine_chart_dashboard_id", sa.UUID(), nullable=True),
        sa.Column("org_id", sa.String(), nullable=True),
        sa.Column("query_params", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["engine_chart_dashboard_id"],
            ["engine_chart_dashboards.id"],
        ),
        sa.ForeignKeyConstraint(
            ["inference_instance_id"],
            ["inference_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inference_instance_model_adapters",
        sa.Column("config_id", sa.UUID(), nullable=True),
        sa.Column("model_adapter_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["inference_instance_config_params.id"],
        ),
        sa.ForeignKeyConstraint(
            ["model_adapter_id"],
            ["model_adapters.id"],
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("inference_instance_model_adapters")
    op.drop_table("inference_instance_dashboards")
    op.drop_table("vectordb_instances")
    op.drop_table("model_adapters")
    op.drop_table("inference_instances")
    op.drop_table("finetunes")
    op.drop_table("engine_default_configs")
    op.drop_table("engine_default_args")
    op.drop_table("engine_chart_dashboards")
    op.drop_table("vectordb")
    op.drop_table("notebooks")
    op.drop_table("models")
    with op.batch_alter_table(
        "inference_instance_config_params", schema=None
    ) as batch_op:
        batch_op.drop_index(
            batch_op.f("ix_inference_instance_config_params_id")
        )

    op.drop_table("inference_instance_config_params")
    op.drop_table("engines")
    op.drop_table("engine_charts")
