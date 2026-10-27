from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    clinicalgov_api_base_url: str = "https://clinicaltrials.gov/api/v2"
    clinicalgov_api_timeout_seconds: float = 30.0
    clinicalgov_mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    clinicalgov_mcp_host: str = "127.0.0.1"
    clinicalgov_mcp_port: int = 8003

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
