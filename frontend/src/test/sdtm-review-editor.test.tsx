import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SDTMReviewEditor } from "@/components/sdtm-review-editor";

const plan = {
  study_name: "SYN-101",
  standard: "SDTMIG 3.4",
  define_standard: "Define-XML 2.1",
  domain_mappings: [{ source_dataset: "RAW_DM", source_type: "raw", target_domain: "DM", relationship: "direct", rationale: "Demographics" }],
  datasets: [{ domain: "DM", description: "Demographics", structure: "One record per subject", key_variables: ["STUDYID", "USUBJID"], variables: [{ name: "AGE", label: "Age", data_type: "Num", source_dataset: "RAW_DM", source_field: "AGE", origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: "Age" }] }],
  domain_rule_augmentations: [{ rule_id: "DM-SOURCE", target_domain: "DM", source_datasets: ["RAW_DM"], description: "Read DM", logic: "Read raw DM", r_input_expression: "raw_dm", sas_input_statement: "set raw.raw_dm;", review_notes: [] }],
  rule_augmentations: [{ rule_id: "DM-AGE", target_domain: "DM", target_variable: "AGE", source_dependencies: ["RAW_DM.AGE"], description: "Map AGE", logic: "Direct", r_expression: '.data[["AGE"]]', sas_expression: "AGE", review_notes: [] }],
  assumptions: [],
  unresolved_mappings: [],
};

describe("SDTMReviewEditor", () => {
  it("presents ordered mapping stages plus separate aCRF and Define-XML review tabs", () => {
    render(<SDTMReviewEditor value={plan} onChange={vi.fn()} onSave={vi.fn()} saving={false} />);

    expect(screen.getByText("Domain mapping")).toBeInTheDocument();
    expect(screen.getAllByText("RAW_DM")).toHaveLength(2);
    fireEvent.click(screen.getByText("Variable & VLM"));
    expect(screen.getByText("Each row is an SDTM variable. Value-level metadata is edited in the VLM column.")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("AGE")).toHaveLength(2);
    fireEvent.click(screen.getByText("Rule augmentation"));
    expect(screen.getByText("DM.AGE")).toBeInTheDocument();
    fireEvent.click(screen.getByText("aCRF review"));
    expect(screen.getByText("No aCRF was generated because this job did not include a blank CRF PDF. Start a new generation with a blank CRF to enable annotation review.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Define-XML"));
    expect(screen.getByText("Define-XML 2.1 review will appear after the SDTM artifacts are generated.")).toBeInTheDocument();
  });
});
