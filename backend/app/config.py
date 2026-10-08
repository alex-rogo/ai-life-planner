from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")
    database_url: str = "postgresql+psycopg://assistant:assistant@localhost:5432/assistant"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    ai_mode: str = Field(default="demo", pattern="^(demo|gemini)$")
    agent_token: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
