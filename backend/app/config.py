from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")
    database_url: str = "postgresql+psycopg://assistant:assistant@localhost:5432/assistant"
    # Empty keeps the original single-user local setup. Set this to a persistent volume
    # directory for the public multi-user deployment.
    workspace_root: str = ""
    clerk_jwt_key: str = ""
    clerk_authorized_parties: str = "https://tomoplanner.app"
    proxy_shared_secret: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # DeepSeek speaks the OpenAI chat-completions protocol.
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    # The fast chat model is the default; a reasoning model can be selected explicitly.
    deepseek_planner_model: str = ""
    # A second provider call can revise a proposal, at the cost of latency and tokens.
    ai_review_enabled: bool = False
    deepseek_base_url: str = "https://api.deepseek.com"
    ai_mode: str = Field(default="demo", pattern="^(demo|gemini|deepseek)$")
    agent_token: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Demo only: pretend the app started at this moment (ISO 8601 with UTC offset), then let the
    # clock run normally. Empty uses the real time.
    demo_now: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
