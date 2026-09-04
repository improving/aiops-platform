import csv
import uuid

from sqlalchemy import MetaData, Table, and_, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from db.database import Base
from logger import setup_logger
from models.engine_chart_dashboards import DBEngineChartDashboards
from models.engine_charts import DBEngineCharts
from models.engines import DBEngine, DBEngineDefaultArgs, DBEngineDefaultConfig
from models.models import DBModel
from models.vectordb import DBVectorDB
from paths import RAW_DATA_DIR
from utils import genid

logger = setup_logger(__name__)


def update_table_definitions(db: Session, engine: Engine):
    connection = engine.connect()
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine)

        for table in Base.metadata.tables.values():
            if table.name in metadata.tables:
                existing_table = Table(
                    table.name, metadata, autoload_with=engine
                )
                existing_columns = set(existing_table.columns.keys())
                model_columns = set(table.columns.keys())

                # Add new columns
                add_update_columns(
                    engine, connection, table, existing_table, existing_columns
                )

                # Drop removed columns
                for column_name in existing_columns - model_columns:
                    logger.info(
                        f"Dropping column {column_name} from table {table.name}"
                    )
                    connection.execute(
                        text(
                            f'ALTER TABLE "{table.name}" DROP COLUMN "{column_name}"'
                        )
                    )
            else:
                logger.info(f"Creating table {table.name}")
                table.create(bind=engine)

        for table_name in metadata.tables.keys():
            if table_name not in Base.metadata.tables:
                logger.info(f"Dropping table {table_name}")
                connection.execute(text(f'DROP TABLE "{table_name}"'))
                connection.commit()

        logger.info("Table definitions updated successfully")
    except Exception as e:
        logger.error(
            f"An error occurred while updating table definitions: {e}"
        )
        db.rollback()
        raise e
    finally:
        db.commit()
        connection.close()
        db.close()


def add_update_columns(
    engine: Engine, connection, table, existing_table, existing_columns
):
    for column in table.columns:
        if column.name not in existing_columns:
            logger.info(f"Adding column {column.name} to table {table.name}")
            connection.execute(
                text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect=engine.dialect)}'
                )
            )
            connection.commit()

        else:
            existing_column = existing_table.columns[column.name]
            if str(column.type) != str(existing_column.type):
                logger.info(
                    f"Updating column {column.name} in table {table.name}. Existing type: {existing_column.type}, New type: {column.type}, compiled type: {column.type.compile(dialect=engine.dialect)}"
                )
                try:
                    connection.execute(
                        text(
                            f'ALTER TABLE "{table.name}" ALTER COLUMN "{column.name}" TYPE {column.type.compile(dialect=engine.dialect)}'
                        )
                    )
                    connection.commit()
                except Exception as e:
                    logger.error(
                        f"Error updating column {column.name} in table {table.name}: {e}"
                    )


def init_db(db: Session, engine: Engine):
    logger.info("Initializing database")
    Base.metadata.create_all(bind=engine)
    update_table_definitions(db, engine)
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
    except Exception as e:
        logger.error(
            f"An error occurred while loading initial data: {e}", exc_info=True
        )
        db.rollback()
    finally:
        db.close()


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


def load_models(db):
    logger.info("Loading models")
    with open(RAW_DATA_DIR / "models.csv", encoding="utf-8") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            model = (
                db.query(DBModel)
                .filter(DBModel.modelId == row["modelId"])
                .first()
            )
            if not model:
                model = DBModel(
                    id=genid.uuid4(),
                    name=row["name"],
                    modelId=row["modelId"],
                    description=row["description"],
                    category=row["category"],
                    subcategory=row["subcategory"],
                    size=int(row["size"]),
                )
                logger.info(f"adding model id: {model.modelId}")
                db.add(model)
            else:
                logger.info(f"Updating model id: {model.modelId}")
                model.name = row["name"]
                model.modelId = row["modelId"]
                model.description = row["description"]
                model.category = row["category"]
                model.subcategory = row["subcategory"]
                model.size = int(row["size"])
    db.commit()


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
        # Delete all tables
        Base.metadata.drop_all(bind=engine)

        # Reload tables and data
        init_db(db, engine)

        logger.info("Data refreshed successfully")
    except Exception as e:
        logger.error(f"An error occurred while refreshing data: {e}")
        db.rollback()
        raise e
