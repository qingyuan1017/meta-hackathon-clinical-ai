from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TLFInventoryOutput(BaseModel):
    output_id: str
    output_type: Literal["table", "listing", "figure"]
    title: str
    basis: Literal["source_supported", "conventional_proposal"] = "source_supported"
    section: str = "Not specified"
    purpose: str = "Not specified"
    population: str = "TODO: confirm population"
    source_reference: str = "TODO: confirm SAP/protocol reference"


class TLFInventoryPlan(BaseModel):
    study_name: str
    analysis_standard: str = "ADaM metadata supplied by user"
    outputs: list[TLFInventoryOutput] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class TLFSourceVariable(BaseModel):
    dataset: str
    variable: str
    role: str = "Analysis input"
    derivation: str = "Direct"


class TLFColumn(BaseModel):
    column_id: str = "COL"
    heading: str
    source: str = "TODO: confirm source"
    statistic: str = ""
    format: str = "TODO: confirm format"


class TLFRow(BaseModel):
    row_id: str
    label: str
    source: str = "TODO: confirm source"
    statistic: str = ""
    condition: str = ""
    format: str = "TODO: confirm format"


class TLFFigureSpec(BaseModel):
    geometry: str = "TODO: confirm figure type"
    x_axis: str = "TODO: confirm x-axis"
    y_axis: str = "TODO: confirm y-axis"
    group: str = ""
    panel: str = ""


class TLFSpec(BaseModel):
    output_id: str
    output_type: Literal["table", "listing", "figure"]
    title: str
    basis: Literal["source_supported", "conventional_proposal"] = "source_supported"
    section: str = "Not specified"
    purpose: str = "Not specified"
    population: str = "TODO: confirm population"
    population_filter: str = "TODO: confirm population filter"
    analysis_datasets: list[str] = Field(default_factory=list)
    source_variables: list[TLFSourceVariable] = Field(default_factory=list)
    selection_criteria: list[str] = Field(default_factory=list)
    treatment_variable: str = "TODO: confirm treatment variable"
    analysis_method: str = "TODO: confirm analysis method"
    columns: list[TLFColumn] = Field(default_factory=list)
    rows: list[TLFRow] = Field(default_factory=list)
    figure: TLFFigureSpec | None = None
    sort_order: list[str] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    display_notes: list[str] = Field(default_factory=list)
    programming_notes: list[str] = Field(default_factory=list)
    source_reference: str = "TODO: confirm SAP/protocol reference"
    readiness: Literal["ready", "blocked"] = "blocked"
    blocking_items: list[str] = Field(default_factory=list)


class TLFAnalysisPlan(BaseModel):
    study_name: str
    analysis_standard: str = "ADaM metadata supplied by user"
    outputs: list[TLFSpec] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class TLFProgramSpec(BaseModel):
    output_id: str
    input_datasets: list[str] = Field(default_factory=list)
    adam_sources: list[TLFSourceVariable] = Field(default_factory=list)
    derivation_steps: list[str] = Field(default_factory=list)
    r_code: str = "# TODO: implement reviewed output logic"
    sas_code: str = "/* TODO: implement reviewed output logic */"
    review_notes: list[str] = Field(default_factory=list)


class TLFProgrammingPlan(BaseModel):
    study_name: str
    programs: list[TLFProgramSpec] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class TLFPlan(TLFAnalysisPlan):
    programs: list[TLFProgramSpec] = Field(min_length=1)
