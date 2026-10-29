import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TLFShellReview, TLFReviewEditor } from "@/components/tlf-review-editor";

const plan = {
  study_name: "SYN-101",
  analysis_standard: "ADaM metadata supplied by user",
  outputs: [{
    output_id: "T-01",
    output_type: "table",
    title: "Change from baseline",
    section: "Efficacy",
    purpose: "Primary endpoint",
    population: "Intent-to-Treat",
    population_filter: "ADSL.ITTFL = 'Y'",
    analysis_datasets: ["ADSL", "ADEFF"],
    source_variables: [{ dataset: "ADEFF", variable: "CHG", role: "Endpoint", derivation: "Derived" }],
    selection_criteria: ["AVISIT = 'Week 12'"],
    treatment_variable: "ADSL.TRT01P",
    analysis_method: "ANCOVA",
    columns: [{ column_id: "TRT", heading: "Treatment", source: "ADSL.TRT01P", statistic: "", format: "text" }],
    rows: [{ row_id: "LSMEAN", label: "LS mean", source: "ADEFF.CHG", statistic: "LS mean", condition: "", format: "8.2" }],
    figure: null,
    sort_order: [], footnotes: [], display_notes: [], programming_notes: [], source_reference: "SAP 7.1",
    readiness: "blocked", blocking_items: ["Confirm missing-data handling"],
  }],
  programs: [{ output_id: "T-01", input_datasets: ["ADSL", "ADEFF"], derivation_steps: ["Join inputs"], r_code: "fit <- lm(CHG ~ TRT01P + BASE)", sas_code: "proc glm; run;", review_notes: [] }],
  assumptions: [], unresolved_items: [],
};

describe("TLFReviewEditor", () => {
  it("requires shell approval before exposing programming augmentation", () => {
    const approve = vi.fn();
    render(<TLFShellReview value={plan} onChange={vi.fn()} onApprove={approve} saving={false} />);

    expect(screen.getByText("TLF shell review required")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "3 · Programming augmentation" })).not.toBeInTheDocument();
    expect(screen.getByText("Approve shell and generate programs")).toBeEnabled();
    fireEvent.click(screen.getByText("Approve shell and generate programs"));
    expect(approve).toHaveBeenCalledWith(expect.not.objectContaining({ programs: expect.anything() }));
  });

  it("separates inventory, analysis/display, and programming into stage tabs", () => {
    const onChange = vi.fn();
    const onSave = vi.fn();
    render(<TLFReviewEditor value={plan} onChange={onChange} onSave={onSave} saving={false} />);

    expect(screen.getByText("TLF review workspace")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "1 · Output inventory" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Output overview")).toBeInTheDocument();
    expect(screen.queryByText("Population and analysis")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "2 · Analysis & display" }));
    expect(screen.getByText("Shell preview")).toBeInTheDocument();
    expect(screen.getByText("Population and analysis")).toBeInTheDocument();
    expect(screen.getByText("Display specification")).toBeInTheDocument();
    expect(screen.queryByText("Programming scaffolds")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "3 · Programming augmentation" }));
    expect(screen.getByText("Programming scaffolds")).toBeInTheDocument();
    expect(screen.getAllByText("blocked").length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("fit <- lm(CHG ~ TRT01P + BASE)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "1 · Output inventory" }));
    fireEvent.click(screen.getByText("Duplicate"));
    expect(onChange).toHaveBeenCalled();
    fireEvent.click(screen.getByText("Save review and rebuild artifacts"));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ study_name: "SYN-101" }));
  });
});
