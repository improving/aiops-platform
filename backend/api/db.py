import csv
import uuid

from api.engine_chart_dashboards import DBEngineChartDashboards
from api.engine_charts import DBEngineCharts
from api.engines import DBEngine
from api.inference_instance import (DBInferenceInstance,
                                    DBInferenceInstanceConfigParams)
from api.models import DBModel
from api.vectordb import DBVectorDB
from logger import setup_logger

from .database import Base, SessionLocal, engine

logger = setup_logger(__name__)


def init_db():
    Base.metadata.create_all(bind=engine)
    load_initial_data()


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
        db.query(DBInferenceInstanceConfigParams).delete()
        db.query(DBInferenceInstance).delete()
        db.query(DBEngine).delete()
        db.query(DBModel).delete()
        db.query(DBEngineCharts).delete()
        db.commit()

        # Delete all tables
        Base.metadata.drop_all(bind=engine)

        # Reload tables and data
        init_db()

        logger.info("Data refreshed successfully")
    except Exception as e:
        logger.error(f"An error occurred while refreshing data: {e}")
        db.rollback()
        raise e
