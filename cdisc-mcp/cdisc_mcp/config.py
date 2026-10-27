from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cdisc_library_api_key: str = ""
    cdisc_library_base_url: str = "https://library.cdisc.org/api"
    cdisc_library_timeout_seconds: float = 30.0
    cdisc_library_cosmos_version: str = "v2"
    cdisc_mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    cdisc_mcp_host: str = "127.0.0.1"
    cdisc_mcp_port: int = 8001

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cdisc_library_configured(self) -> bool:
        return bool(self.cdisc_library_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
