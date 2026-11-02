from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .artifacts import ArtifactRead
from .reviews import ReviewPatchRead
from .sdtm_workbench import SDTMWorkbenchState


class JobRead(BaseModel):
    id: str
    workflow: str
    title: str
    status: str
    model_name: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    review_stage: Literal[
        "edc_source",
        "domain_mapping",
        "domain_mapping_completed",
        "variable_mapping",
        "variable_mapping_domain",
        "rule_augmentation_domain",
        "tlf_inventory",
        "tlf_shell",
        "tlf_programming",
    ] | None = None
    result: dict | list | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    artifacts: list[ArtifactRead] = Field(default_factory=list)
    sdtm_workbench: SDTMWorkbenchState | None = None
    result_revision: str | None = None
    review_patch: ReviewPatchRead | None = None


class JobList(BaseModel):
    items: list[JobRead]
    total: int
    page: int
    page_size: int


class JobResultUpdate(BaseModel):
    result: dict[str, Any]
