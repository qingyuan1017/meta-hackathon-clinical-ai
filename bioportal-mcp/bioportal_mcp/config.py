from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bioportal_api_key: str = ""
    bioportal_api_base_url: str = "https://data.bioontology.org"
    bioportal_api_timeout_seconds: float = 30.0
    bioportal_mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    bioportal_mcp_host: str = "127.0.0.1"
    bioportal_mcp_port: int = 8004

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def bioportal_configured(self) -> bool:
        return bool(self.bioportal_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
