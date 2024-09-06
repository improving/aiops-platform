import csv
import uuid
from .database import SessionLocal, engine, Base
from api.models import DBModel
from api.engines import DBEngine
from api.inference_instance import DBInferenceInstance, DBInferenceInstanceConfigParams

def init_db():
    Base.metadata.create_all(bind=engine)
    load_initial_data()

def load_initial_data():
    db = SessionLocal()
    try:
        # Load models
        if db.query(DBModel).count() == 0:
            with open('raw_data/models.csv', 'r') as f:
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
                        description=row['description'],
                        helm_chart_repo=row['helm_chart_repo'],
                        helm_chart_name=row['helm_chart_name']
                    )
                    db.add(engine)

        db.commit()
    except Exception as e:
        print(f"An error occurred while loading initial data: {e}")
        db.rollback()
    finally:
        db.close()

def reload_data():
    db = SessionLocal()
    try:
        # Clear existing data
        db.query(DBEngine).delete()
        db.query(DBModel).delete()

        # Reload data
        load_initial_data()

        print("Data reloaded successfully")
    except Exception as e:
        print(f"An error occurred while reloading data: {e}")
        db.rollback()
    finally:
        db.close()
