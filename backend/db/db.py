import csv
import uuid

import yaml
from sqlalchemy import MetaData, and_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from db.migrate import upgrade_to_head
from logger import setup_logger
from models.engine_chart_dashboards import DBEngineChartDashboards
from models.engine_charts import DBEngineCharts
from models.engines import DBEngine, DBEngineDefaultArgs, DBEngineDefaultConfig
from models.mcp_catalog import (
    EGRESS_PUBLIC,
    SOURCE_BUILTIN,
    McpCatalogEntry,
    builtin_id,
)
from models.mcp_catalog import STATUS_PUBLISHED as CATALOG_PUBLISHED
from models.models import STATUS_PUBLISHED, DBModel
from models.serving_option import ServingOption
from models.vectordb import DBVectorDB
from paths import RAW_DATA_DIR
from utils import genid
from utils.mcp_catalog_settings import normal_setting

logger = setup_logger(__name__)


def init_db(db: Session, engine: Engine):
    logger.info("Initializing database")
    upgrade_to_head(engine)
    load_initial_data(db)
    logger.info("Database initialized successfully")


def load_initial_data(db: Session):
    try:
        # Load models
        load_models(db)

        # Load engines
        load_engines(db)

        # Load engine charts
        load_engine_charts(db)

        # Load engine chart dashboards
        load_engine_chart_dashboards(db)

        # Load engine default configs
        load_engine_default_configs(db)

        # Load engine default args
        load_engine_default_args(db)

        # Load vector dbs
        load_vector_dbs(db)
        load_mcp_catalog(db)
    except Exception as e:
        logger.error(
            f"An error occurred while loading initial data: {e}", exc_info=True
        )
        db.rollback()
    finally:
        db.close()


def load_mcp_catalog(db, path=None):
    """Seed the deploy catalog from ``raw_data/mcp_catalog.yaml``.
    A builtin row is found by ``(source, source_id)``, as ``load_models``
    finds its rows, and an entry somebody imported is never touched. A
    seed name that another row holds is skipped with a warning: ``name``
    is unique, and a taken name must not stop the startup. A builtin
    entry is the repository's: what a platform admin changed on one
    (all but its ``status``) is written over at the next start."""
    logger.info("Loading the MCP catalog")
    with open(
        path or RAW_DATA_DIR / "mcp_catalog.yaml", encoding="utf-8"
    ) as f:
        document = yaml.safe_load(f) or {}
    for item in document.get("entries") or []:
        name = item["name"]
        row = (
            db.query(McpCatalogEntry)
            .filter(
                McpCatalogEntry.source == SOURCE_BUILTIN,
                McpCatalogEntry.source_id == name,
            )
            .first()
        )
        if row is None:
            taken = (
                db.query(McpCatalogEntry.id)
                .filter(McpCatalogEntry.name == name)
                .first()
            )
            if taken is not None:
                logger.warning(
                    "MCP catalog: the name %s is taken by an imported "
                    "entry; the builtin one is skipped",
                    name,
                )
                continue
            row = McpCatalogEntry(
                id=builtin_id(name),
                name=name,
                source=SOURCE_BUILTIN,
                source_id=name,
                status=CATALOG_PUBLISHED,
            )
            db.add(row)
        row.title = item["title"]
        row.description = item.get("description")
        row.docs_url = item.get("docs_url")
        row.image = item["image"]
        row.tag = item["tag"]
        row.command = item.get("command") or []
        row.args = item.get("args") or []
        row.port = int(item["port"])
        row.path = item.get("path") or "/mcp"
        row.settings = [normal_setting(s) for s in item.get("settings") or []]
        row.egress = item.get("egress") or EGRESS_PUBLIC
        row.chart_repo = item["chart_repo"]
        row.chart_name = item["chart_name"]
        row.notes = []
    db.commit()


def load_vector_dbs(db):
    logger.info("Loading vector dbs")
    with open(RAW_DATA_DIR / "vectordb.csv", encoding="utf-8") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            _vectordb = (
                db.query(DBVectorDB)
                .filter(DBVectorDB.name == row["name"])
                .first()
            )
            if not _vectordb:
                _vectordb = DBVectorDB(
                    id=genid.uuid4(),
                    name=row["name"],
                    description=row["description"],
                    chart_repo=row["chart_repo"],
                    chart_name=row["chart_name"],
                )
                logger.info(f"adding vector db id: {_vectordb.name}")
                db.add(_vectordb)
            else:
                logger.info(f"Updating vector db: {_vectordb.name}")
                _vectordb.name = row["name"]
                _vectordb.description = row["description"]
                _vectordb.chart_repo = row["chart_repo"]
                _vectordb.chart_name = row["chart_name"]
    db.commit()


def load_engine_chart_dashboards(db):
    logger.info("Loading engine chart dashboards")
    with open(
        RAW_DATA_DIR / "engine_chart_dashboards.csv", encoding="utf-8"
    ) as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            _engine_chart_dashboard = (
                db.query(DBEngineChartDashboards)
                .filter(
                    and_(
                        DBEngineChartDashboards.engine_chart_id
                        == uuid.UUID(row["engine_chart_id"]),
                        DBEngineChartDashboards.panel_id == row["panel_id"],
                    )
                )
                .first()
            )
            if not _engine_chart_dashboard:
                _engine_chart_dashboard = DBEngineChartDashboards(
                    id=genid.uuid4(),
                    dashboard_id=row["dashboard_id"],
                    dashboard_name=row["dashboard_name"],
                    engine_id=uuid.UUID(row["engine_id"]),
                    engine_chart_id=uuid.UUID(row["engine_chart_id"]),
                    panel_id=row["panel_id"],
                    panel_name=row["panel_name"],
                )
                logger.info(
                    f"adding engine chart dashboard id: {_engine_chart_dashboard.id}"
                )
                db.add(_engine_chart_dashboard)
            else:
                logger.info(
                    f"Updating engine chart dashboard: {_engine_chart_dashboard.id}"
                )
                _engine_chart_dashboard.dashboard_id = row["dashboard_id"]
                _engine_chart_dashboard.dashboard_name = row["dashboard_name"]
                _engine_chart_dashboard.engine_id = uuid.UUID(row["engine_id"])
                _engine_chart_dashboard.engine_chart_id = uuid.UUID(
                    row["engine_chart_id"]
                )
                _engine_chart_dashboard.panel_id = row["panel_id"]
                _engine_chart_dashboard.panel_name = row["panel_name"]
    db.commit()


def load_engine_charts(db):
    logger.info("Loading engine charts")
    with open(RAW_DATA_DIR / "engine_charts.csv", encoding="utf-8") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            _engine_chart = (
                db.query(DBEngineCharts)
                .filter(DBEngineCharts.id == uuid.UUID(row["id"]))
                .first()
            )
            if not _engine_chart:
                _engine_chart = DBEngineCharts(
                    id=uuid.UUID(row["id"]),
                    engine=row["engine"],
                    chart_type=row["chart_type"],
                    chart_repo=row["chart_repo"],
                    chart_name=row["chart_name"],
                    chart_version=row["chart_version"],
                )
                logger.info(f"adding engine chart id: {_engine_chart.id}")
                db.add(_engine_chart)
            else:
                logger.info(f"Updating engine chart: {_engine_chart.id}")
                _engine_chart.engine = row["engine"]
                _engine_chart.chart_type = row["chart_type"]
                _engine_chart.chart_repo = row["chart_repo"]
                _engine_chart.chart_name = row["chart_name"]
                _engine_chart.chart_version = row["chart_version"]
    db.commit()


def load_engines(db: Session):
    logger.info("Loading engines")
    with open(RAW_DATA_DIR / "engines.csv", encoding="utf-8") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            _engine = (
                db.query(DBEngine).filter(DBEngine.name == row["name"]).first()
            )
            if not _engine:
                _engine = DBEngine(
                    id=uuid.UUID(row["id"]),
                    name=row["name"],
                    llm_support=bool(row["llm_support"]),
                    embedding_support=bool(row["embedding_support"]),
                    reranking_support=bool(row["reranking_support"]),
                    prompt_guard_support=bool(row["prompt_guard_support"]),
                    vector_db_support=bool(row["vector_db_support"]),
                    cpu=bool(row.get("cpu")),
                )
                logger.info(f"adding engine name: {_engine.name}")
                db.add(_engine)
            else:
                logger.info(f"Updating engine: {_engine.name}")
                _engine.name = row["name"]
                _engine.llm_support = bool(row["llm_support"])
                _engine.embedding_support = bool(row["embedding_support"])
                _engine.reranking_support = bool(row["reranking_support"])
                _engine.prompt_guard_support = bool(
                    row["prompt_guard_support"]
                )
                _engine.vector_db_support = bool(row["vector_db_support"])
                _engine.cpu = bool(row.get("cpu"))
    db.commit()


def load_engine_default_configs(db):
    logger.info("Loading engine default configs")
    with open(
        RAW_DATA_DIR / "engine_default_configs.csv", encoding="utf-8"
    ) as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            _engine_default_config = (
                db.query(DBEngineDefaultConfig)
                .filter(
                    DBEngineDefaultConfig.engine_id
                    == uuid.UUID(row["engine_id"]),
                    DBEngineDefaultConfig.name == row["name"],
                )
                .first()
            )
            if not _engine_default_config:
                _engine_default_config = DBEngineDefaultConfig(
                    id=genid.uuid4(),
                    engine_id=uuid.UUID(row["engine_id"]),
                    chart_type=row["chart_type"],
                    name=row["name"],
                    defaultValue=row["defaultValue"],
                    editable=bool(row["editable"]),
                )
                logger.info(
                    f"adding engine default config id: {_engine_default_config.id}"
                )
                db.add(_engine_default_config)
            else:
                logger.info(
                    f"Updating engine default config: {_engine_default_config.id}"
                )
                _engine_default_config.engine_id = uuid.UUID(row["engine_id"])
                _engine_default_config.chart_type = row["chart_type"]
                _engine_default_config.name = row["name"]
                _engine_default_config.defaultValue = row["defaultValue"]
                _engine_default_config.editable = bool(row["editable"])
    db.commit()


def load_engine_default_args(db):
    logger.info("Loading engine default args")
    with open(RAW_DATA_DIR / "engine_default_args.csv", encoding="utf-8") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            _engine_default_arg = (
                db.query(DBEngineDefaultArgs)
                .filter(
                    DBEngineDefaultArgs.engine_id
                    == uuid.UUID(row["engine_id"]),
                    DBEngineDefaultArgs.name == row["name"],
                )
                .first()
            )
            if not _engine_default_arg:
                _engine_default_arg = DBEngineDefaultArgs(
                    id=genid.uuid4(),
                    engine_id=uuid.UUID(row["engine_id"]),
                    chart_type=row["chart_type"],
                    name=row["name"],
                    defaultValue=row["defaultValue"],
                    editable=bool(row["editable"]),
                )
                logger.info(
                    f"adding engine default arg id: {_engine_default_arg.id}"
                )
                db.add(_engine_default_arg)
            else:
                logger.info(
                    f"Updating engine default arg: {_engine_default_arg.id}"
                )
                _engine_default_arg.engine_id = uuid.UUID(row["engine_id"])
                _engine_default_arg.chart_type = row["chart_type"]
                _engine_default_arg.name = row["name"]
                _engine_default_arg.defaultValue = row["defaultValue"]
                _engine_default_arg.editable = bool(row["editable"])
    db.commit()


def load_models(db, path=None):
    """Seed the global catalog from ``raw_data/models.yaml`` (or
    ``path``, for tests -- ``registry/export.py`` writes the same shape
    back out). Upserts by ``(source, source_id)`` when ``source_id`` is
    set, else by ``modelId``, and never deletes a row: a model or
    serving option removed from the YAML stays in the database until an
    admin removes it."""
    logger.info("Loading models")
    with open(path or RAW_DATA_DIR / "models.yaml", encoding="utf-8") as f:
        document = yaml.safe_load(f) or {}
    for entry in document.get("models") or []:
        _load_model_entry(db, entry)
    db.commit()


def _find_model_for_entry(db, entry) -> DBModel | None:
    source = entry.get("source") or "manual"
    source_id = entry.get("source_id")
    if source_id:
        return (
            db.query(DBModel)
            .filter(DBModel.source == source, DBModel.source_id == source_id)
            .first()
        )
    return (
        db.query(DBModel).filter(DBModel.modelId == entry["model_id"]).first()
    )


def _load_model_entry(db, entry):
    model = _find_model_for_entry(db, entry)
    if not model:
        model = DBModel(id=genid.uuid4())
        logger.info(f"adding model id: {entry['model_id']}")
        db.add(model)
    else:
        logger.info(f"Updating model id: {entry['model_id']}")

    model.name = entry["name"]
    model.modelId = entry["model_id"]
    model.description = entry.get("description")
    model.category = entry.get("category")
    model.subcategory = entry.get("subcategory")
    model.size = entry.get("size")
    model.source = entry.get("source") or "manual"
    model.source_id = entry.get("source_id")
    model.license = entry.get("license")
    model.parameters = entry.get("parameters")
    model.context_length = entry.get("context_length")
    model.capabilities = entry.get("capabilities") or []
    model.formats = entry.get("formats") or []
    model.tags = entry.get("tags") or []
    model.status = entry.get("status") or STATUS_PUBLISHED
    # The serving options below need model.id, which only exists once
    # a new row has been flushed.
    db.flush()

    for option in entry.get("serving_options") or []:
        _load_serving_option_entry(db, model, option)


def _load_serving_option_entry(db, model, option):
    row = (
        db.query(ServingOption)
        .filter(
            ServingOption.model_id == model.id,
            ServingOption.engine == option["engine"],
        )
        .first()
    )
    if not row:
        row = ServingOption(model_id=model.id, engine=option["engine"])
        db.add(row)
    row.reference = option["reference"]
    row.default_args = option.get("default_args")


def reload_data(db: Session):
    try:
        # Reload data
        load_initial_data(db)

        logger.info("Data reloaded successfully")
    except Exception as e:
        logger.error(f"An error occurred while reloading data: {e}")
        db.rollback()
        raise e
    finally:
        db.close()


def refresh_db(db: Session, engine: Engine):
    try:
        # Drop every table, alembic_version included, so the
        # migrations run again from scratch.
        existing = MetaData()
        existing.reflect(bind=engine)
        existing.drop_all(bind=engine)

        # Reload tables and data
        init_db(db, engine)

        logger.info("Data refreshed successfully")
    except Exception as e:
        logger.error(f"An error occurred while refreshing data: {e}")
        db.rollback()
        raise e
