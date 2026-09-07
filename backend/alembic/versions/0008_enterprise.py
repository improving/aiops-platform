"""Enterprise: invitations, audit events, personal API tokens, and the
status, failure reason and resource columns on the instance tables.

Adds ``invitations`` (#13), ``audit_events`` (#14) and ``api_tokens``
(#18), ``memberships.created_at`` and ``invited_by`` (#13), and on
``inference_instances`` the platform-written ``status``,
``last_error``, ``last_error_at`` and ``stopped_at`` plus the
launch-time ``replicas``, ``gpu_count``, ``cpu`` and ``memory``
(#15, #16); ``vectordb_instances`` and ``notebooks`` get the same four
status columns.

No data step: ``status`` NULL means "derive from the pod as before",
and the operations stream starts writing it. Every constraint is
named so the SQLite batch downgrade can drop it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_status_columns(batch_op) -> None:
    """The four columns shared by the three instance tables."""
    batch_op.add_column(sa.Column("status", sa.String(), nullable=True))
    batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
    batch_op.add_column(
        sa.Column("last_error_at", sa.DateTime(), nullable=True)
    )
    batch_op.add_column(sa.Column("stopped_at", sa.DateTime(), nullable=True))


def _drop_status_columns(batch_op) -> None:
    batch_op.drop_column("stopped_at")
    batch_op.drop_column("last_error_at")
    batch_op.drop_column("last_error")
    batch_op.drop_column("status")


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_user_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_invitations_org_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name="fk_invitations_invited_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_user_id"],
            ["users.id"],
            name="fk_invitations_accepted_user_id_users",
        ),
        sa.UniqueConstraint(
            "org_id", "email", name="uq_invitations_org_email"
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_label", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_kind", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("outcome", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_audit_events_org_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_events_actor_id_users"
        ),
    )
    # Named as SQLAlchemy names an ``index=True`` column, so the model
    # and the database agree and autogenerate stays quiet.
    op.create_index("ix_audit_events_at", "audit_events", ["at"])
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_api_tokens_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_api_tokens_org_id_organizations",
        ),
        sa.UniqueConstraint("prefix", name="uq_api_tokens_prefix"),
    )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(sa.Column("invited_by", sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_memberships_invited_by_users",
            "users",
            ["invited_by"],
            ["id"],
        )

    with op.batch_alter_table("inference_instances") as batch_op:
        _add_status_columns(batch_op)
        batch_op.add_column(
            sa.Column(
                "replicas", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch_op.add_column(
            sa.Column(
                "gpu_count", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch_op.add_column(sa.Column("cpu", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("memory", sa.String(), nullable=True))

    with op.batch_alter_table("vectordb_instances") as batch_op:
        _add_status_columns(batch_op)

    with op.batch_alter_table("notebooks") as batch_op:
        _add_status_columns(batch_op)


def downgrade() -> None:
    with op.batch_alter_table("notebooks") as batch_op:
        _drop_status_columns(batch_op)

    with op.batch_alter_table("vectordb_instances") as batch_op:
        _drop_status_columns(batch_op)

    with op.batch_alter_table("inference_instances") as batch_op:
        batch_op.drop_column("memory")
        batch_op.drop_column("cpu")
        batch_op.drop_column("gpu_count")
        batch_op.drop_column("replicas")
        _drop_status_columns(batch_op)

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint(
            "fk_memberships_invited_by_users", type_="foreignkey"
        )
        batch_op.drop_column("invited_by")
        batch_op.drop_column("created_at")

    op.drop_table("api_tokens")
    op.drop_index("ix_audit_events_org_id", table_name="audit_events")
    op.drop_index("ix_audit_events_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("invitations")
