import csv
import uuid

from sqlalchemy import MetaData, Table, text

from api.engine_chart_dashboards import DBEngineChartDashboards
from api.engine_charts import DBEngineCharts
from api.engines import DBEngine
from api.inference_instance import (DBInferenceInstance,
                                    DBInferenceInstanceConfigParams)
from api.models import DBModel
from api.vectordb import DBVectorDB
from api.vectordb_instance import DBVectorDBInstance
from logger import setup_logger
from models.notebook import Notebook

from .database import Base, SessionLocal, engine

logger = setup_logger(__name__)


def update_table_definitions():
    db = SessionLocal()
    connection = engine.connect()
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine)

        for table in Base.metadata.tables.values():
            if table.name in metadata.tables:
                existing_table = Table(table.name,
                                       metadata,
                                       autoload_with=engine)
                existing_columns = set(existing_table.columns.keys())
                model_columns = set(table.columns.keys())

                # Add new columns
                add_update_columns(connection, table, existing_table,
                                   existing_columns)

                # Drop removed columns
                for column_name in existing_columns - model_columns:
                    logger.info(
                        f"Dropping column {column_name} from table {table.name}"
                    )
                    connection.execute(
                        text(
                            f'ALTER TABLE "{table.name}" DROP COLUMN "{column_name}"'
                        ))
            else:
                logger.info(f"Creating table {table.name}")
                table.create(bind=engine)

        for table_name in metadata.tables.keys():
            if table_name not in Base.metadata.tables:
                logger.info(f"Dropping table {table_name}")
                connection.execute(text(f'DROP TABLE "{table_name}"'))

        logger.info("Table definitions updated successfully")
    except Exception as e:
        logger.error(
            f"An error occurred while updating table definitions: {e}")
        db.rollback()
        raise e
    finally:
        db.commit()
        connection.close()
        db.close()


def add_update_columns(connection, table, existing_table, existing_columns):
    for column in table.columns:
        if column.name not in existing_columns:
            logger.info(f"Adding column {column.name} to table {table.name}")
            connection.execute(
                text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect=engine.dialect)}'
                ))
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
                        ))
                    connection.commit()
                except Exception as e:
                    logger.error(
                        f"Error updating column {column.name} in table {table.name}: {e}"
                    )


def init_db():
    logger.info("Initializing database")
    Base.metadata.create_all(bind=engine)
    update_table_definitions()
    load_initial_data()
    logger.info("Database initialized successfully")


def load_initial_data():
    db = SessionLocal()
    try:
        # Load models
        logger.info("Loading models")
        if db.query(DBModel).count() == 0:
            with open("raw_data/models.csv", "r", encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    model = DBModel(
                        id=uuid.uuid4(),
                        name=row["name"],
                        modelId=row["modelId"],
                        description=row["description"],
                        category=row["category"],
                        subcategory=row["subcategory"],
                        size=int(row["size"]),
                    )
                    db.add(model)
        db.commit()

        # Load engines
        logger.info("Loading engines")
        if db.query(DBEngine).count() == 0:
            with open("raw_data/engines.csv", "r", encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    _engine = DBEngine(
                        id=uuid.UUID(row["id"]),
                        name=row["name"],
                        llm_support=bool(row["llm_support"]),
                        embedding_support=bool(row["embedding_support"]),
                        reranking_support=bool(row["reranking_support"]),
                        prompt_guard_support=bool(row["prompt_guard_support"]),
                        vector_db_support=bool(row["vector_db_support"]),
                    )
                    db.add(_engine)
        db.commit()

        # Load engine charts
        logger.info("Loading engine charts")
        if db.query(DBEngineCharts).count() == 0:
            with open("raw_data/engine_charts.csv", "r",
                      encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    engine_chart = DBEngineCharts(
                        id=uuid.UUID(row["id"]),
                        engine=row["engine"],
                        chart_type=row["chart_type"],
                        chart_repo=row["chart_repo"],
                        chart_name=row["chart_name"],
                    )
                    db.add(engine_chart)
        db.commit()

        # Load engine chart dashboards
        logger.info("Loading engine chart dashboards")
        if db.query(DBEngineChartDashboards).count() == 0:
            with open("raw_data/engine_chart_dashboards.csv",
                      "r",
                      encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    engine_chart_dashboard = DBEngineChartDashboards(
                        id=uuid.uuid4(),
                        dashboard_id=row["dashboard_id"],
                        dashboard_name=row["dashboard_name"],
                        engine_id=uuid.UUID(row["engine_id"]),
                        engine_chart_id=uuid.UUID(row["engine_chart_id"]),
                        panel_id=row["panel_id"],
                        panel_name=row["panel_name"],
                    )
                    db.add(engine_chart_dashboard)
        db.commit()

        # Load vector dbs
        logger.info("Loading vector dbs")
        if db.query(DBVectorDB).count() == 0:
            with open("raw_data/vectordb.csv", "r", encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    vectordb = DBVectorDB(
                        id=uuid.uuid4(),
                        name=row["name"],
                        description=row["description"],
                        chart_repo=row["chart_repo"],
                        chart_name=row["chart_name"],
                    )
                    db.add(vectordb)

        db.commit()
    except Exception as e:
        logger.error(f"An error occurred while loading initial data: {e}")
        db.rollback()
    finally:
        db.close()


def reload_data():
    db = SessionLocal()

    try:
        # Clear existing data
        db.query(DBInferenceInstanceConfigParams).delete()
        db.query(DBInferenceInstance).delete()
        db.query(DBEngineChartDashboards).delete()
        db.query(DBVectorDBInstance).delete()
        db.query(DBVectorDB).delete()
        db.query(Notebook).delete()
        db.query(DBEngineCharts).delete()
        db.query(DBEngine).delete()
        db.query(DBModel).delete()
        db.query(DBEngineCharts).delete()
        db.commit()

        # Reload data
        load_initial_data()

        logger.info("Data reloaded successfully")
    except Exception as e:
        logger.error(f"An error occurred while reloading data: {e}")
        db.rollback()
        raise e
    finally:
        db.close()


def refresh_db():
    db = SessionLocal()
    try:
        # Delete all tables
        Base.metadata.drop_all(bind=engine)

        # Reload tables and data
        init_db()

        logger.info("Data refreshed successfully")
    except Exception as e:
        logger.error(f"An error occurred while refreshing data: {e}")
        db.rollback()
        raise e
