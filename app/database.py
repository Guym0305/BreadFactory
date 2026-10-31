from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

Base = declarative_base()
settings = get_settings()


def _prepare_sqlite_path(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    raw = url.removeprefix("sqlite:///")
    if raw in ("", ":memory:"):
        return
    Path(raw).parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(settings.database_url)

connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    poolclass=NullPool,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _enable_sqlite(dbapi_connection, _connection_record) -> None:
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.fetchone()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def _begin_immediate(connection) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")


if settings.database_url.startswith("sqlite"):
    event.listen(engine, "connect", _enable_sqlite)
    event.listen(engine, "begin", _begin_immediate)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
