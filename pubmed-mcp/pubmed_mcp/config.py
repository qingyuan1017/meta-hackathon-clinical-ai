from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    pubmed_email: str = ""
    pubmed_api_key: str = ""
    pubmed_tool: str = "clinical_ai_pubmed_mcp"
    pubmed_api_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    pubmed_api_timeout_seconds: float = 30.0
    pubmed_max_results: int = 20
    pubmed_mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    pubmed_mcp_host: str = "127.0.0.1"
    pubmed_mcp_port: int = 8005

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def pubmed_configured(self) -> bool:
        return bool(self.pubmed_email.strip())

    @property
    def pubmed_api_key_configured(self) -> bool:
        return bool(self.pubmed_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
