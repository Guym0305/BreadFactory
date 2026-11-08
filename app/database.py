from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

Base = declarative_base()
settings = get_settings()


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite:")


def _prepare_sqlite_path(url: str) -> None:
    if not _is_sqlite(url):
        return
    raw = url.removeprefix("sqlite:///")
    if raw in ("", ":memory:"):
        return
    Path(raw).parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(settings.database_url)

connect_args: dict = {}
engine_kwargs: dict = {
    "pool_pre_ping": True,
}
if _is_sqlite(settings.database_url):
    connect_args["check_same_thread"] = False
    engine_kwargs["poolclass"] = NullPool
else:
    # Cloud Run: small pool; connections are short-lived per request.
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 5

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    **engine_kwargs,
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


if _is_sqlite(settings.database_url):
    event.listen(engine, "connect", _enable_sqlite)
    event.listen(engine, "begin", _begin_immediate)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
