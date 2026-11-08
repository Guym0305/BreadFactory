import logging
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings

logger = logging.getLogger(__name__)


def _describe_database_url(url: str) -> str:
    """Safe summary for logs (no password)."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    host = (query.get("host") or [parsed.hostname or ""])[0]
    db = (parsed.path or "/").lstrip("/") or "(none)"
    return f"dialect={parsed.scheme} database={db} host={host or '(default)'}"


def run_migrations() -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", (root / "alembic").as_posix())
    config.set_main_option("prepend_sys_path", root.as_posix())
    settings = get_settings()
    try:
        command.upgrade(config, "head")
    except SQLAlchemyError as exc:
        target = _describe_database_url(settings.database_url)
        root_exc = exc.__cause__ or exc
        logger.exception("Database migration failed (%s): %s", target, root_exc)
        raise RuntimeError(
            f"Cannot connect for migrations ({target}). "
            "On Cloud Run check: Cloud SQL connection attached, "
            "DATABASE_URL user/password/db name, database 'bakery' exists, "
            "and the runtime SA has Cloud SQL Client. "
            f"Driver error: {root_exc}"
        ) from exc
