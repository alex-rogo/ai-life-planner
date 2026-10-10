from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")
    database_url: str = ""
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "assistant"
    database_user: str = "assistant"
    database_password: str = "assistant"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    ai_mode: str = Field(default="demo", pattern="^(demo|gemini)$")
    agent_token: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @model_validator(mode="after")
    def resolve_database_url(self):
        if not self.database_url:
            password = quote_plus(self.database_password)
            self.database_url = (
                f"postgresql+psycopg://{self.database_user}:{password}"
                f"@{self.database_host}:{self.database_port}/{self.database_name}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
