from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Clinical AI Artifact Workbench"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    data_dir: Path = Path("data")
    frontend_origin: str = "http://localhost:3000"
    meta_api_key: str = ""
    meta_api_base_url: str = "https://api.meta.ai/v1"
    meta_model: str = ""
    meta_transcription_model: str = "muse-voice-transcribe-1.0"
    max_audio_mb: int = 16
    transcription_timeout_seconds: int = 300
    agent_max_turns: int = 20
    agent_max_remote_tool_calls: int = 6
    cdisc_mcp_enabled: bool = True
    cdisc_mcp_url: str = "http://127.0.0.1:8001/mcp"
    clinicalgov_mcp_enabled: bool = True
    clinicalgov_mcp_url: str = "http://127.0.0.1:8003/mcp"
    clinicalgov_max_tool_rounds: int = 3
    openfda_mcp_enabled: bool = True
    openfda_mcp_url: str = "http://127.0.0.1:8765/mcp"
    openfda_max_tool_rounds: int = 3
    bioportal_mcp_enabled: bool = True
    bioportal_mcp_url: str = "http://127.0.0.1:8004/mcp"
    bioportal_max_tool_rounds: int = 3
    pubmed_mcp_enabled: bool = True
    pubmed_mcp_url: str = "http://127.0.0.1:8005/mcp"
    pubmed_max_tool_rounds: int = 3
    max_file_mb: int = 25
    max_pdf_pages: int = 200
    ai_timeout_seconds: int = 180
    max_source_chunks: int = 8
    chunk_characters: int = 12_000
    core_cli_path: Path = Path("/opt/cdisc-core/core.py")
    core_timeout_seconds: int = 600
    core_pool_size: int = 2

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'workbench.db').as_posix()}"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_api_key.strip() and self.meta_model.strip())

    @property
    def meta_voice_configured(self) -> bool:
        return bool(self.meta_api_key.strip() and self.meta_transcription_model.strip())

    @property
    def meta_transcription_url(self) -> str:
        return f"{self.meta_api_base_url.rstrip('/')}/asr/transcribe"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
