"""Grow the models table into a registry with serving options.

Adds the registry fields to ``models`` (source, license, parameters,
context length, capabilities, formats, tags, status, sync bookkeeping,
``org_id``), the ``model_serving_options`` table (which engine can run
an entry and with which reference), and ``inference_instances.reference``
(Phase 3 Task 1: the option's reference, when an instance is launched
from one).

The data step backfills every existing ``models`` row to
``source="manual"``, ``status="published"``, ``capabilities`` derived
from ``category``, ``formats`` from whether ``modelId`` looks like an
Ollama tag (a ``:`` and no ``/``), and one serving option per row and
compatible engine (Ollama tags -> Ollama; other ``llm`` rows ->
HuggingFace, vLLM, NIM; ``embedding``/``reranker`` -> HuggingFace, NIM;
``prompt_guard`` -> OPEA). A row with no ``category`` (a pre-registry
row inserted without one) gets empty capabilities and no serving
options beyond the Ollama-tag case.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-05 22:00:00.000000

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# category -> capabilities; a category outside this map (or NULL) gets
# no capabilities.
_CAPABILITIES: dict[str, list[str]] = {
    "llm": ["chat"],
    "embedding": ["embedding"],
    "reranker": ["rerank"],
    "prompt_guard": ["guard"],
}

# category -> the serving-option engines besides the Ollama-tag case.
_EXTRA_ENGINES: dict[str, tuple[str, ...]] = {
    "llm": ("HuggingFace", "vLLM", "NIM"),
    "embedding": ("HuggingFace", "NIM"),
    "reranker": ("HuggingFace", "NIM"),
    "prompt_guard": ("OPEA",),
}

# Lightweight table objects, typed so the UUID/JSON binds are rendered
# the way the app writes them on both SQLite and Postgres.
models = sa.table(
    "models",
    sa.column("id", sa.UUID()),
    sa.column("modelId", sa.String()),
    sa.column("category", sa.String()),
    sa.column("capabilities", sa.JSON()),
    sa.column("formats", sa.JSON()),
)

serving_options = sa.table(
    "model_serving_options",
    sa.column("id", sa.UUID()),
    sa.column("model_id", sa.UUID()),
    sa.column("engine", sa.String()),
    sa.column("reference", sa.String()),
    sa.column("created_at", sa.DateTime()),
)


def _is_ollama_tag(model_id: str) -> bool:
    """An Ollama tag such as ``qwen3:0.6b``: a ``:`` and no ``/``."""
    return ":" in model_id and "/" not in model_id


def upgrade() -> None:
    with op.batch_alter_table("models") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source",
                sa.String(),
                nullable=False,
                server_default="manual",
            )
        )
        batch_op.add_column(sa.Column("source_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("license", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("parameters", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("context_length", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "capabilities",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "formats",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="published",
            )
        )
        batch_op.add_column(
            sa.Column("synced_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sync_error", sa.String(), nullable=True)
        )
        batch_op.add_column(sa.Column("raw", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("org_id", sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_models_org_id_organizations",
            "organizations",
            ["org_id"],
            ["id"],
        )

    with op.batch_alter_table("inference_instances") as batch_op:
        batch_op.add_column(sa.Column("reference", sa.String(), nullable=True))

    op.create_table(
        "model_serving_options",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("default_args", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
            name="fk_model_serving_options_model_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "model_id", "engine", name="uq_serving_options_model_engine"
        ),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.select(models.c.id, models.c.modelId, models.c.category)
    ).all()
    for model_id, model_id_value, category in rows:
        model_id_value = model_id_value or ""
        capabilities = _CAPABILITIES.get(category, [])
        is_ollama_tag = _is_ollama_tag(model_id_value)
        formats = ["gguf"] if is_ollama_tag else ["safetensors"]
        conn.execute(
            models.update()
            .where(models.c.id == model_id)
            .values(
                # capabilities/formats are typed sa.JSON() above, which
                # serializes a Python list on its own; json.dumps()-ing
                # it here first would double-encode it into a string.
                capabilities=capabilities,
                formats=formats,
            )
        )
        engines = (
            ["Ollama"]
            if is_ollama_tag
            else list(_EXTRA_ENGINES.get(category, ()))
        )
        for engine in engines:
            conn.execute(
                serving_options.insert().values(
                    id=uuid.uuid4(),
                    model_id=model_id,
                    engine=engine,
                    reference=model_id_value,
                    created_at=datetime.now(),
                )
            )


def downgrade() -> None:
    op.drop_table("model_serving_options")

    with op.batch_alter_table("inference_instances") as batch_op:
        batch_op.drop_column("reference")

    with op.batch_alter_table("models") as batch_op:
        batch_op.drop_constraint(
            "fk_models_org_id_organizations", type_="foreignkey"
        )
        batch_op.drop_column("org_id")
        batch_op.drop_column("raw")
        batch_op.drop_column("sync_error")
        batch_op.drop_column("synced_at")
        batch_op.drop_column("status")
        batch_op.drop_column("tags")
        batch_op.drop_column("formats")
        batch_op.drop_column("capabilities")
        batch_op.drop_column("context_length")
        batch_op.drop_column("parameters")
        batch_op.drop_column("license")
        batch_op.drop_column("source_id")
        batch_op.drop_column("source")
