import csv
import uuid

from sqlalchemy import Boolean

from api.engine_charts import DBEngineCharts
from .database import SessionLocal, engine, Base
from api.models import DBModel
from api.engines import DBEngine
from api.inference_instance import DBInferenceInstance, DBInferenceInstanceConfigParams
from logger import setup_logger

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
            with open('raw_data/models.csv', 'r') as f:
                logger.info("Loading models")
                logger.info(f"Loading models from {f}")
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    model = DBModel(
                        id=uuid.uuid4(),
                        name=row['name'],
                        modelId=row['modelId'],
                        description=row['description'],
                        category=row['category'],
                        subcategory=row['subcategory'],
                        size=int(row['size'])
                    )
                    db.add(model)

        # Load engines
        if db.query(DBEngine).count() == 0:
            with open('raw_data/engines.csv', 'r') as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    engine = DBEngine(
                        id=uuid.uuid4(),
                        name=row['name'],
                        llm_support=bool(row['llm_support']),
                        embedding_support=bool(row['embedding_support']),
                        reranking_support=bool(row['reranking_support'])
                    )
                    db.add(engine)

        # Load engine charts
        if db.query(DBEngineCharts).count() == 0:
            with open('raw_data/engine_charts.csv', 'r') as f:
                csv_reader = csv.DictReader(f)
                for row in csv_reader:
                    engine_chart = DBEngineCharts(
                        id=uuid.uuid4(),
                        engine=row['engine'],
                        chart_type=row['chart_type'],
                        chart_repo=row['chart_repo'],
                        chart_name=row['chart_name']
                    )
                    db.add(engine_chart)

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