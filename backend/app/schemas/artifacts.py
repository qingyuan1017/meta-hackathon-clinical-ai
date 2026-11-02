from __future__ import annotations

from pydantic import BaseModel, Field


class ArtifactPackageMemberRead(BaseModel):
    path: str
    size_bytes: int
    is_directory: bool = False


class ArtifactRead(BaseModel):
    id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    download_url: str
    package_members: list[ArtifactPackageMemberRead] = Field(default_factory=list)
