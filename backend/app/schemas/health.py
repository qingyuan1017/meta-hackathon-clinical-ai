from __future__ import annotations

from pydantic import BaseModel

from .common import DISCLAIMER


class HealthRead(BaseModel):
    status: str
    database: str
    storage: str
    object_storage: str
    meta_configured: bool
    meta_base_url: str
    meta_model: str | None
    meta_transcription_model: str | None
    disclaimer: str = DISCLAIMER
