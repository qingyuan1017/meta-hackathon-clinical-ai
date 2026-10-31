from __future__ import annotations

from pydantic import BaseModel


class ArtifactRead(BaseModel):
    id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    download_url: str
