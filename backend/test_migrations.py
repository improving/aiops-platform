import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.orm import configure_mappers, sessionmaker

from db.database import Base
from db.db import refresh_db
from db.migrate import alembic_config, upgrade_to_head
from models.api_token import ApiToken
from models.audit_event import AuditEvent
from models.inference_instance import DBInferenceInstance
from models.invitation import Invitation
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG
from models.user import User

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
    sa.column("category", sa.String()),
    sa.column("capabilities", sa.JSON()),
    sa.column("formats", sa.JSON()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

# The 0007 registry table, typed the same way.
serving_options_table = sa.table(
    "model_serving_options",
    sa.column("id", sa.UUID()),
    sa.column("model_id", sa.UUID()),
    sa.column("engine", sa.String()),
    sa.column("reference", sa.String()),
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

# The 0008 enterprise tables and the columns it adds to existing ones.
ENTERPRISE_TABLES = ("invitations", "audit_events", "api_tokens")
ENTERPRISE_COLUMNS: dict[str, set[str]] = {
    "memberships": {"created_at", "invited_by"},
    "inference_instances": {
        "status",
        "last_error",
        "last_error_at",
        "replicas",
        "gpu_count",
        "cpu",
        "memory",
        "stopped_at",
    },
    "vectordb_instances": {
        "status",
        "last_error",
        "last_error_at",
        "stopped_at",
    },
    "notebooks": {"status", "last_error", "last_error_at", "stopped_at"},
}

# A pre-0008 inference instance row, typed like the tables above.
inference_instances_table = sa.table(
    "inference_instances",
    sa.column("id", sa.UUID()),
    sa.column("status", sa.String()),
    sa.column("replicas", sa.Integer()),
    sa.column("gpu_count", sa.Integer()),
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


def index_names(engine, table):
    return {i["name"] for i in sa.inspect(engine).get_indexes(table)}


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
    # A mis-numbered file would still satisfy the dynamic check above.
    assert head_revision() == "0015"
    assert {"organizations", "users", "memberships"} <= table_names(engine)
    assert "model_serving_options" in table_names(engine)
    assert "reference" in column_names(engine, "inference_instances")
    for column in ("source", "status", "capabilities", "formats", "tags"):
        assert column in column_names(engine, "models"), column
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


def test_registry_migration_seeds_serving_options_from_category_and_model_id(
    tmp_path,
):
    """0007's data step: an Ollama tag gets one Ollama serving option, a
    Hugging Face-style llm id gets HuggingFace, vLLM and NIM."""
    engine = make_engine(tmp_path)
    with engine.begin() as conn:
        command.upgrade(alembic_config(conn), "0006")

    ollama_id = uuid.uuid4()
    hf_id = uuid.uuid4()
    now = datetime.now()
    with engine.begin() as conn:
        conn.execute(
            models_table.insert(),
            [
                {
                    "id": ollama_id,
                    "name": "Qwen3 0.6B",
                    "modelId": "qwen3:0.6b",
                    "category": "llm",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": hf_id,
                    "name": "Llama 3.1 8B Instruct",
                    "modelId": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                    "category": "llm",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )

    upgrade_to_head(engine)

    assert current_revision(engine) == head_revision() == "0015"
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                serving_options_table.c.model_id,
                serving_options_table.c.engine,
                serving_options_table.c.reference,
            )
        ).all()
    by_model: dict = {}
    for model_id, option_engine, reference in rows:
        by_model.setdefault(model_id, []).append((option_engine, reference))

    assert by_model[ollama_id] == [("Ollama", "qwen3:0.6b")]
    assert set(by_model[hf_id]) == {
        ("HuggingFace", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
        ("vLLM", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
        ("NIM", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
    }

    # capabilities/formats are JSON-typed columns: the data step must
    # pass Python lists through them, not pre-json.dumps()-ed strings,
    # which the column would then double-encode.
    with engine.connect() as conn:
        capabilities_and_formats = conn.execute(
            sa.select(
                models_table.c.capabilities, models_table.c.formats
            ).where(models_table.c.id == ollama_id)
        ).one()
    assert capabilities_and_formats == (["chat"], ["gguf"])


def test_registry_migration_tolerates_a_row_with_no_category(tmp_path):
    """A pre-registry row inserted without a category (the shape
    test_upgrade_stamps_database_created_by_the_old_code seeds) must not
    make the data step raise, and gets no serving options."""
    engine = make_engine(tmp_path)
    with engine.begin() as conn:
        command.upgrade(alembic_config(conn), BASELINE_REVISION)
    model_id = seed_model(engine)

    upgrade_to_head(engine)

    assert current_revision(engine) == head_revision()
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(serving_options_table.c.id).where(
                serving_options_table.c.model_id == model_id
            )
        ).all()
    assert rows == []


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


def test_metadata_declares_the_enterprise_tables():
    """The model files the streams import declare the tables and
    columns of 0008, ``Membership.user`` still resolves now that
    ``memberships`` has two foreign keys to ``users``, and the
    NOT NULL resource counts carry the same server default as the
    migration."""
    configure_mappers()

    assert Invitation.__tablename__ == "invitations"
    assert AuditEvent.__tablename__ == "audit_events"
    assert ApiToken.__tablename__ == "api_tokens"
    assert set(ENTERPRISE_TABLES) <= set(Base.metadata.tables)
    for table, columns in ENTERPRISE_COLUMNS.items():
        declared = set(Base.metadata.tables[table].columns.keys())
        assert columns <= declared, table

    assert Membership.user.property.mapper.class_ is User
    assert DBInferenceInstance.__table__.c.replicas.server_default.arg == "1"
    assert DBInferenceInstance.__table__.c.gpu_count.server_default.arg == "1"
    assert AuditEvent.__table__.c.at.index is True
    assert AuditEvent.__table__.c.org_id.index is True


def test_enterprise_migration_adds_tables_and_columns_and_downgrades(
    tmp_path,
):
    """0008: the three tables and every added column exist at head and
    match the model files column for column, and one downgrade step
    removes all of them again (SQLite batch mode, which recreates the
    table, so named constraints matter)."""
    engine = make_engine(tmp_path)

    upgrade_to_head(engine)

    assert current_revision(engine) == head_revision() == "0015"
    assert set(ENTERPRISE_TABLES) <= table_names(engine)
    assert column_names(engine, "invitations") == {
        "id",
        "org_id",
        "email",
        "role",
        "invited_by",
        "created_at",
        "accepted_at",
        "accepted_user_id",
    }
    assert column_names(engine, "audit_events") == {
        "id",
        "at",
        "org_id",
        "actor_id",
        "actor_label",
        "action",
        "resource_kind",
        "resource_id",
        "outcome",
        "request_id",
        "detail",
    }
    assert column_names(engine, "api_tokens") == {
        "id",
        "user_id",
        "org_id",
        "name",
        "prefix",
        "token_hash",
        "scope",
        "created_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
    }
    assert {"ix_audit_events_at", "ix_audit_events_org_id"} <= index_names(
        engine, "audit_events"
    )
    for table, columns in ENTERPRISE_COLUMNS.items():
        assert columns <= column_names(engine, table), table
    # The streams import the models and the database runs 0008: the
    # two must agree on every column name of every table this
    # migration touches.
    for table in ENTERPRISE_TABLES + tuple(ENTERPRISE_COLUMNS):
        declared = set(Base.metadata.tables[table].columns.keys())
        assert column_names(engine, table) == declared, table

    with engine.begin() as conn:
        command.downgrade(alembic_config(conn), "0007")

    assert current_revision(engine) == "0007"
    assert not set(ENTERPRISE_TABLES) & table_names(engine)
    for table, columns in ENTERPRISE_COLUMNS.items():
        assert not columns & column_names(engine, table), table


def test_enterprise_migration_defaults_replicas_and_gpu_count(tmp_path):
    """A row that exists before 0008 reads replicas 1, gpu_count 1 and
    status NULL afterwards: the NOT NULL server defaults survive the
    SQLite batch recreate."""
    engine = make_engine(tmp_path)
    with engine.begin() as conn:
        command.upgrade(alembic_config(conn), "0007")
    instance_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(inference_instances_table.insert().values(id=instance_id))

    upgrade_to_head(engine)

    with engine.connect() as conn:
        row = conn.execute(
            sa.select(
                inference_instances_table.c.status,
                inference_instances_table.c.replicas,
                inference_instances_table.c.gpu_count,
            ).where(inference_instances_table.c.id == instance_id)
        ).one()
    assert row == (None, 1, 1)


def test_mcp_migration_matches_the_models_and_downgrades(tmp_path):
    """0009 and 0010: the two MCP tables carry exactly the declared columns, the
    shared credential is one per server, and the downgrade removes
    both."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mcp.db'}")
    upgrade_to_head(engine)
    for table in ("mcp_servers", "mcp_credentials", "mcp_oauth_states"):
        declared = set(Base.metadata.tables[table].columns.keys())
        assert column_names(engine, table) == declared, table
    assert {
        "uq_mcp_credentials_shared",
        "uq_mcp_credentials_user",
    } <= index_names(engine, "mcp_credentials")

    with engine.begin() as conn:
        command.downgrade(alembic_config(conn), "0008")
    assert current_revision(engine) == "0008"
    assert not {
        "mcp_servers",
        "mcp_credentials",
        "mcp_oauth_states",
    } & table_names(engine)
