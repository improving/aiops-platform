import os
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from paths import TMP_DIR
from utils import genid


class Base(DeclarativeBase):
    pass


def setup_engine():
    if os.environ.get("TEST_MODE", "false").lower() == "true":
        # Per test database in tmp folder
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        DATABASE_URL = (
            f"sqlite:///{TMP_DIR / f'test_database_{genid.uuid4()}.db'}"
        )
    else:
        DATABASE_URL = os.environ.get(
            "DATABASE_URL", "sqlite:///./database.db"
        )

    if DATABASE_URL.startswith("sqlite"):
        return create_engine(DATABASE_URL)

    if DATABASE_URL.startswith("postgresql"):
        DATABASE_NAME = os.environ.get("DATABASE_NAME", "postgres")
        DATABASE_USER = os.environ.get("DATABASE_USER", "postgres")
        DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "postgres")
        DATABASE_HOST, DATABASE_PORT = (
            DATABASE_URL.split("://")[1].split(":")[0],
            5432,
        )
        if ":" in DATABASE_URL.split("://")[1]:
            DATABASE_PORT = (
                DATABASE_URL.split("://")[1].split(":")[1].split("/")[0]
            )
        url = URL.create(
            "postgresql+psycopg2",
            username=DATABASE_USER,
            password=DATABASE_PASSWORD,
            host=DATABASE_HOST,
            port=DATABASE_PORT,
            database=DATABASE_NAME,
        )
        return create_engine(url)

    raise ValueError("DATABASE_URL must be a postgres or sqlite URL")


@lru_cache
def get_engine() -> Engine:
    return setup_engine()


@lru_cache
def get_sessionmaker() -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db_direct() -> Session:
    return get_sessionmaker()()


def get_db():
    db = get_db_direct()
    try:
        yield db
    finally:
        db.close()
