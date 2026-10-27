from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    workbench_api_url: str = "http://127.0.0.1:8000/api/v1"
    workbench_api_timeout_seconds: float = 60.0
    workbench_mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    workbench_mcp_host: str = "127.0.0.1"
    workbench_mcp_port: int = 8002

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
