from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations() -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", (root / "alembic").as_posix())
    config.set_main_option("prepend_sys_path", root.as_posix())
    command.upgrade(config, "head")
