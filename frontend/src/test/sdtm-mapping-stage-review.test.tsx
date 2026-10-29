import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SDTMDomainMappingReview, SDTMVariableMappingReview } from "@/components/sdtm-mapping-stage-review";

const source = {
  study_name: "SYN-101",
  datasets: [{ name: "RAW_DM", label: "Demographics", source_type: "raw" }],
};
const domain = {
  study_name: "SYN-101",
  standard: "SDTMIG 3.4",
  domain_mappings: [{ source_dataset: "RAW_DM", source_type: "raw", target_domain: "DM", relationship: "direct", rationale: "Demographics source" }],
  assumptions: [],
  unresolved_mappings: [],
};
const variable = {
  study_name: "SYN-101",
  standard: "SDTMIG 3.4",
  define_standard: "Define-XML 2.1",
  datasets: [{ domain: "DM", description: "Demographics", structure: "One record per subject", key_variables: ["USUBJID"], variables: [{ name: "AGE", label: "Age", data_type: "Num", source_dataset: "RAW_DM", source_field: "AGE", origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null }] }],
  assumptions: [],
  unresolved_mappings: [],
};

describe("SDTM mapping review gates", () => {
  it("blocks at a dedicated domain review before variable mapping", () => {
    const approve = vi.fn();
    render(<SDTMDomainMappingReview value={{ source_spec: source, domain_mapping: domain }} onChange={vi.fn()} onApprove={approve} saving={false} />);

    expect(screen.getByText("Domain mapping review required")).toBeInTheDocument();
    expect(screen.getByText("Approved source inventory")).toBeInTheDocument();
    expect(screen.getAllByText("RAW_DM")).toHaveLength(2);
    fireEvent.click(screen.getByText("Approve domains and build variable mapping"));
    expect(approve).toHaveBeenCalledWith(domain);
  });

  it("presents variable rows with VLM cells before rule generation", () => {
    const approve = vi.fn();
    render(<SDTMVariableMappingReview value={{ source_spec: source, domain_mapping: domain, variable_mapping: variable }} onChange={vi.fn()} onApprove={approve} saving={false} />);

    expect(screen.getByText("Variable and value-level mapping review required")).toBeInTheDocument();
    expect(screen.getByText("VLM cells")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("AGE")).toHaveLength(2);
    fireEvent.click(screen.getByText("Approve mappings and generate rules/code"));
    expect(approve).toHaveBeenCalledWith(variable);
  });
});
