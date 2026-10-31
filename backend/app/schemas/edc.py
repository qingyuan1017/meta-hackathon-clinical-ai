from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EDCVisit(BaseModel):
    name: str
    timing: str = "Not specified"
    forms: list[str] = Field(default_factory=list)


class EDCField(BaseModel):
    field_id: str
    label: str
    data_type: Literal["text", "integer", "decimal", "date", "datetime", "boolean", "coded"] = "text"
    required: bool = False
    codelist: str | None = None
    derivation: str | None = None
    instructions: str | None = None


class EDCForm(BaseModel):
    form_id: str
    name: str
    purpose: str = ""
    fields: list[EDCField]


class CodeList(BaseModel):
    name: str
    values: list[str]


class EditCheck(BaseModel):
    check_id: str
    form: str
    field: str
    condition: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class EDCDesign(BaseModel):
    study_name: str
    visits: list[EDCVisit]
    forms: list[EDCForm]
    codelists: list[CodeList] = Field(default_factory=list)
    edit_checks: list[EditCheck] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class EDCSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EDCSourceProvenance(EDCSourceModel):
    file: str = Field(min_length=1)
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)


class EDCSourceVariable(EDCSourceModel):
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    data_type: Literal["text", "integer", "decimal", "date", "datetime", "boolean", "coded", "unknown"] = (
        "unknown"
    )
    length: int | None = Field(default=None, ge=1)
    format: str | None = None
    required: bool = False
    codelist: str | None = None
    form_id: str | None = None
    question: str | None = None
    provenance: EDCSourceProvenance


class EDCSourceDataset(EDCSourceModel):
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    source_type: Literal["raw", "sdtm"] = "raw"
    structure: str = "Not specified"
    key_variables: list[str] = Field(default_factory=list)
    variables: list[EDCSourceVariable] = Field(min_length=1)
    provenance: EDCSourceProvenance


class EDCSourceCodeList(EDCSourceModel):
    name: str = Field(min_length=1)
    values: list[str] = Field(default_factory=list)


class EDCSourceSpecification(EDCSourceModel):
    study_name: str = Field(min_length=1)
    datasets: list[EDCSourceDataset] = Field(min_length=1)
    codelists: list[EDCSourceCodeList] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
