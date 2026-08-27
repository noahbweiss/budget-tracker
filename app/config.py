"""Central place for configuration. Reads from .env / environment variables.

TODO: nothing yet — settings are minimal until features are built out.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/finance.db"
    simplefin_access_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
