from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Local: sqlite:///./data/bakery.db
    # Cloud SQL instance bread-factory-514112:me-west1:breadfactory (Cloud Run Unix socket):
    # postgresql+psycopg://USER:PASSWORD@/bakery?host=/cloudsql/bread-factory-514112:me-west1:breadfactory
    database_url: str = "sqlite:///./data/bakery.db"
    cloud_sql_instance: str = "bread-factory-514112:me-west1:breadfactory"
    public_base_url: str = "http://127.0.0.1:8000"
    slot_capacity: int = 20
    payment_hold_minutes: int = 30
    session_secret: str = "dev-bread-factory-session-change-me"
    admin_username: str = "Admin"
    admin_password: str = "Admin"
    grow_api_key: str = ""
    grow_page_code: str = ""
    grow_user_id: str = ""
    grow_api_url: str = "https://api.grow.co.il/v1/page/create"
    grow_webhook_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def grow_enabled(self) -> bool:
        return bool(self.grow_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
