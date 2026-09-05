import sqlalchemy as sa

from core import create_app
from db.database import get_db_direct
from db.db import load_models
from db.migrate import upgrade_to_head
from paths import RAW_DATA_DIR
from registry.export import export_registry


def _fresh_sqlite_engine(tmp_path, name="registry_export.db"):
    engine = sa.create_engine(f"sqlite:///{tmp_path / name}")
    upgrade_to_head(engine)
    return engine


def test_export_of_the_seeded_database_round_trips_through_load_models(
    tmp_path,
):
    """export_registry(db) on the app's seeded database, loaded back
    into a fresh database with load_models, produces the same rows and
    serving options."""
    create_app()  # seeds the shared TEST_MODE database
    seeded_db = get_db_direct()
    try:
        exported = export_registry(seeded_db)
    finally:
        seeded_db.close()
    assert exported  # the seeded catalog is not empty

    yaml_path = tmp_path / "exported.yaml"
    yaml_path.write_text(exported, encoding="utf-8")

    engine = _fresh_sqlite_engine(tmp_path, "round-trip.db")
    session = sa.orm.sessionmaker(bind=engine)()
    try:
        load_models(session, path=yaml_path)
        reexported = export_registry(session)
    finally:
        session.close()

    assert reexported == exported


def test_committed_models_yaml_equals_its_own_export(tmp_path):
    """A guard against hand-edited YAML the exporter would reorder: the
    committed raw_data/models.yaml must already be in the exporter's
    canonical order and shape, since anyone can hand-edit it in a
    review, and load_models never rewrites the file."""
    engine = _fresh_sqlite_engine(tmp_path)
    session = sa.orm.sessionmaker(bind=engine)()
    try:
        load_models(session, path=RAW_DATA_DIR / "models.yaml")
        exported = export_registry(session)
    finally:
        session.close()

    committed = (RAW_DATA_DIR / "models.yaml").read_text(encoding="utf-8")
    assert exported == committed


def test_load_models_upserts_by_model_id_without_deleting_other_rows(
    tmp_path,
):
    """A row absent from a later load stays; a row present is updated
    in place, matched by modelId when source_id is unset."""
    engine = _fresh_sqlite_engine(tmp_path)
    session = sa.orm.sessionmaker(bind=engine)()
    first_yaml = tmp_path / "first.yaml"
    first_yaml.write_text(
        "version: 1\n"
        "models:\n"
        "- name: Old Name\n"
        "  model_id: org/one\n"
        "  source: manual\n"
        "  source_id: null\n"
        "  description: null\n"
        "  category: llm\n"
        "  subcategory: null\n"
        "  size: 1\n"
        "  license: null\n"
        "  parameters: null\n"
        "  context_length: null\n"
        "  capabilities: [chat]\n"
        "  formats: [safetensors]\n"
        "  tags: []\n"
        "  status: published\n"
        "  serving_options:\n"
        "  - engine: HuggingFace\n"
        "    reference: org/one\n"
        "    default_args: null\n"
        "- name: Untouched\n"
        "  model_id: org/two\n"
        "  source: manual\n"
        "  source_id: null\n"
        "  description: null\n"
        "  category: llm\n"
        "  subcategory: null\n"
        "  size: 1\n"
        "  license: null\n"
        "  parameters: null\n"
        "  context_length: null\n"
        "  capabilities: [chat]\n"
        "  formats: [safetensors]\n"
        "  tags: []\n"
        "  status: published\n"
        "  serving_options: []\n",
        encoding="utf-8",
    )
    try:
        load_models(session, path=first_yaml)

        second_yaml = tmp_path / "second.yaml"
        second_yaml.write_text(
            "version: 1\n"
            "models:\n"
            "- name: New Name\n"
            "  model_id: org/one\n"
            "  source: manual\n"
            "  source_id: null\n"
            "  description: null\n"
            "  category: llm\n"
            "  subcategory: null\n"
            "  size: 2\n"
            "  license: null\n"
            "  parameters: null\n"
            "  context_length: null\n"
            "  capabilities: [chat]\n"
            "  formats: [safetensors]\n"
            "  tags: []\n"
            "  status: published\n"
            "  serving_options:\n"
            "  - engine: HuggingFace\n"
            "    reference: org/one-renamed\n"
            "    default_args: null\n",
            encoding="utf-8",
        )
        load_models(session, path=second_yaml)

        exported = export_registry(session)
    finally:
        session.close()

    assert "New Name" in exported
    assert "org/one-renamed" in exported
    # "org/two" was not in the second load: it must not be deleted.
    assert "Untouched" in exported
