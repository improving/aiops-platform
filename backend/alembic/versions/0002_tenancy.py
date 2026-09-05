"""Tenancy: organizations, users, memberships; org_id and owner_id.

Every resource table gets a nullable ``org_id`` and ``owner_id``, the
``default`` organization is created and every existing row is moved
into it. ``inference_instance_dashboards.org_id`` is Grafana's
organization id and is not touched.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04 23:37:14.154764

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed so the organization is the same on every database. It starts
# with a letter on purpose: SQLite gives UUID columns numeric affinity
# and would store an all-digit hex string as a number.
DEFAULT_ORG_ID = uuid.UUID("de5a0170-0000-4000-8000-000000000001")
DEFAULT_ORG_SLUG = "default"

# Tables that belong to an organization and an owner.
TENANT_TABLES = (
    "notebooks",
    "vectordb_instances",
    "inference_instances",
    "finetunes",
    "model_adapters",
)

# Lightweight table objects, typed so the UUID binds are rendered the
# way the app writes them (CHAR(32) on SQLite, uuid on Postgres).
organizations = sa.table(
    "organizations",
    sa.column("id", sa.UUID()),
    sa.column("slug", sa.String()),
    sa.column("name", sa.String()),
    sa.column("created_at", sa.DateTime()),
)


def tenant_table(name: str) -> sa.TableClause:
    return sa.table(name, sa.column("org_id", sa.UUID()))


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("idp_org_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sub", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sub", name="uq_users_sub"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "org_id", name="uq_membership_user_org"
        ),
    )

    with op.batch_alter_table("vectordb_instances") as batch_op:
        batch_op.add_column(
            sa.Column("api_endpoint", sa.String(), nullable=True)
        )

    for table in TENANT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("org_id", sa.UUID(), nullable=True))
            batch_op.add_column(
                sa.Column("owner_id", sa.UUID(), nullable=True)
            )
            batch_op.create_foreign_key(
                f"fk_{table}_org_id_organizations",
                "organizations",
                ["org_id"],
                ["id"],
            )
            batch_op.create_foreign_key(
                f"fk_{table}_owner_id_users", "users", ["owner_id"], ["id"]
            )

    conn = op.get_bind()
    conn.execute(
        organizations.insert().values(
            id=DEFAULT_ORG_ID,
            slug=DEFAULT_ORG_SLUG,
            name="Default",
            created_at=datetime.now(),
        )
    )
    for table in TENANT_TABLES:
        tenant = tenant_table(table)
        conn.execute(
            tenant.update()
            .where(tenant.c.org_id.is_(None))
            .values(org_id=DEFAULT_ORG_ID)
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(
                f"fk_{table}_owner_id_users", type_="foreignkey"
            )
            batch_op.drop_constraint(
                f"fk_{table}_org_id_organizations", type_="foreignkey"
            )
            batch_op.drop_column("owner_id")
            batch_op.drop_column("org_id")

    with op.batch_alter_table("vectordb_instances") as batch_op:
        batch_op.drop_column("api_endpoint")

    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
