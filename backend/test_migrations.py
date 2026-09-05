import uuid

import sqlalchemy as sa
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.orm import sessionmaker

from db.db import refresh_db
from db.migrate import alembic_config, upgrade_to_head
from models.organization import DEFAULT_ORG_SLUG

BASELINE_REVISION = "0001"
TENANT_TABLES = (
    "notebooks",
    "vectordb_instances",
    "inference_instances",
    "finetunes",
    "model_adapters",
)

# A pre-0002 row, typed so the UUID binds on SQLite and Postgres alike.
models_table = sa.table(
    "models",
    sa.column("id", sa.UUID()),
    sa.column("name", sa.String()),
    sa.column("modelId", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

organizations_table = sa.table(
    "organizations",
    sa.column("id", sa.UUID()),
    sa.column("slug", sa.String()),
)

# The notebooks table as the baseline had it, without org_id.
notebooks_table = sa.table(
    "notebooks",
    sa.column("id", sa.UUID()),
    sa.column("name", sa.String()),
    sa.column("namespace", sa.String()),
    sa.column("type", sa.String()),
    sa.column("nvidia_gpu", sa.Boolean()),
)


def make_engine(tmp_path):
    # Not setup_engine(): in TEST_MODE that consumes a genid value and
    # shifts the ids the snapshot tests expect.
    return sa.create_engine(f"sqlite:///{tmp_path / 'migrations.db'}")


def current_revision(engine):
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision():
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def table_names(engine):
    return set(sa.inspect(engine).get_table_names())


def column_names(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def organizations(engine):
    with engine.connect() as conn:
        return conn.execute(
            sa.select(organizations_table.c.id, organizations_table.c.slug)
        ).all()


def seed_model(engine):
    model_id = uuid.uuid4()
    now = sa.func.now()
    with engine.begin() as conn:
        conn.execute(
            models_table.insert().values(
                id=model_id,
                name="seed",
                modelId="org/seed",
                created_at=now,
                updated_at=now,
            )
        )
    return model_id


def test_upgrade_fresh_database(tmp_path):
    engine = make_engine(tmp_path)

    upgrade_to_head(engine)

    assert {"models", "engines", "notebooks", "alembic_version"} <= (
        table_names(engine)
    )
    assert current_revision(engine) == head_revision()
    assert {"organizations", "users", "memberships"} <= table_names(engine)
    for table in TENANT_TABLES:
        assert {"org_id", "owner_id"} <= column_names(engine, table), table
    assert "api_endpoint" in column_names(engine, "vectordb_instances")
    # inference_instance_dashboards.org_id is Grafana's org id, untouched.
    assert "owner_id" not in column_names(
        engine, "inference_instance_dashboards"
    )
    assert [slug for _, slug in organizations(engine)] == [DEFAULT_ORG_SLUG]


def test_upgrade_stamps_database_created_by_the_old_code(tmp_path):
    engine = make_engine(tmp_path)
    with engine.begin() as conn:
        command.upgrade(alembic_config(conn), BASELINE_REVISION)
        # The old code had the baseline tables but no Alembic bookkeeping.
        conn.execute(sa.text("DELETE FROM alembic_version"))
    model_id = seed_model(engine)
    notebook_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            notebooks_table.insert().values(
                id=notebook_id,
                name="nb",
                namespace="ai-stack",
                type="jupyter",
                nvidia_gpu=False,
            )
        )
    assert current_revision(engine) is None

    upgrade_to_head(engine)

    assert current_revision(engine) == head_revision()
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(models_table.c.id, models_table.c.name)
        ).all()
    assert rows == [(model_id, "seed")]
    [(default_org_id, _)] = organizations(engine)
    with engine.connect() as conn:
        backfilled = (
            conn.execute(sa.text("SELECT org_id FROM notebooks"))
            .scalars()
            .all()
        )
    assert backfilled == [default_org_id.hex]


def test_upgrade_twice_is_a_no_op(tmp_path):
    engine = make_engine(tmp_path)
    upgrade_to_head(engine)
    model_id = seed_model(engine)

    upgrade_to_head(engine)

    assert current_revision(engine) == head_revision()
    with engine.connect() as conn:
        ids = conn.execute(sa.select(models_table.c.id)).scalars().all()
    assert ids == [model_id]
    assert len(organizations(engine)) == 1


def test_refresh_db_leaves_a_clean_upgraded_schema(tmp_path):
    engine = make_engine(tmp_path)
    upgrade_to_head(engine)
    seed_model(engine)
    db = sessionmaker(bind=engine)()
    try:
        refresh_db(db, engine)
    finally:
        db.close()

    assert current_revision(engine) == head_revision()
    with engine.connect() as conn:
        names = conn.execute(sa.select(models_table.c.name)).scalars().all()
    assert "seed" not in names
    assert names, "load_initial_data seeds the models table"
    assert [slug for _, slug in organizations(engine)] == [DEFAULT_ORG_SLUG]
