from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentSection(BaseModel):
    heading: str
    body: str
    review_notes: list[str] = Field(default_factory=list)


class ClinicalDocument(BaseModel):
    document_type: str
    title: str
    version: str = "Draft 0.1"
    executive_summary: str
    sections: list[DocumentSection]
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
