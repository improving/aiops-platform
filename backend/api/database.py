import os

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine():
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./database.db")
    if DATABASE_URL.startswith("sqlite"):
        return create_engine(DATABASE_URL)

    if DATABASE_URL.startswith("postgresql"):
        DATABASE_NAME = os.environ.get("DATABASE_NAME", "postgres")
        DATABASE_USER = os.environ.get("DATABASE_USER", "postgres")
        DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "postgres")
        DATABASE_HOST, DATABASE_PORT = DATABASE_URL.split("://")[1].split(
            ":")[0], 5432
        if ":" in DATABASE_URL.split("://")[1]:
            DATABASE_PORT = DATABASE_URL.split("://")[1].split(":")[1].split(
                "/")[0]
        url = URL.create("postgresql+psycopg2",
                         username=DATABASE_USER,
                         password=DATABASE_PASSWORD,
                         host=DATABASE_HOST,
                         port=DATABASE_PORT,
                         database=DATABASE_NAME)
        return create_engine(url)

    raise ValueError("DATABASE_URL must be a postgres or sqlite URL")


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
