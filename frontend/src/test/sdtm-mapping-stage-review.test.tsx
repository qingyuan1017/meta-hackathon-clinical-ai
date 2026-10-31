import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { SDTMDomainMappingReview, SDTMVariableMappingReview } from "@/components/sdtm-mapping-stage-review";
import { ReviewDraftProvider } from "@/lib/review-draft-context";
import type { Job } from "@/lib/types";

const source = {
  study_name: "SYN-101",
  datasets: [{ name: "RAW_DM", label: "Demographics", source_type: "raw" }],
};
const domain = {
  study_name: "SYN-101",
  standard: "SDTMIG 3.4",
  domain_mappings: [{ source_dataset: "RAW_DM", source_type: "raw", target_domain: "DM", relationship: "direct", rationale: "Demographics source" }],
  unmapped_datasets: [],
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
    expect(approve).toHaveBeenCalledWith(expect.objectContaining({
      datasets: [expect.objectContaining({ domain: "DM", variables: variable.datasets[0].variables })],
    }));
  });

  it("shows only the active domain's owned mapping comments", () => {
    const owned = {
      ...variable,
      assumptions: ["DM assumption", "AE assumption"],
      unresolved_mappings: ["DM decision", "AE decision"],
      datasets: [
        { ...variable.datasets[0], review_assumptions: ["DM assumption"], review_unresolved_mappings: ["DM decision"] },
        { domain: "AE", description: "Adverse Events", structure: "One record per event", key_variables: ["USUBJID", "AESEQ"], review_assumptions: ["AE assumption"], review_unresolved_mappings: ["AE decision"], variables: [{ name: "AETERM", label: "Reported Term", data_type: "Char", source_dataset: "RAW_DM", source_field: "AGE", origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null }] },
      ],
    };
    render(<SDTMVariableMappingReview value={{ source_spec: source, domain_mapping: domain, variable_mapping: owned }} onChange={vi.fn()} onApprove={vi.fn()} saving={false} />);

    expect(screen.getByText("DM mapping comments")).toBeInTheDocument();
    expect(screen.getByDisplayValue("DM assumption")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("AE assumption")).not.toBeInTheDocument();
    const dmDecisions = screen.getByRole("region", { name: "DM feedback decisions" });
    expect(within(dmDecisions).getByText("DM decision")).toBeInTheDocument();
    expect(within(dmDecisions).queryByText("AE decision")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "AE feedback decisions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "AE" }));
    expect(screen.getByText("AE mapping comments")).toBeInTheDocument();
    expect(screen.getByDisplayValue("AE assumption")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("DM assumption")).not.toBeInTheDocument();
    const aeDecisions = screen.getByRole("region", { name: "AE feedback decisions" });
    expect(within(aeDecisions).getByText("AE decision")).toBeInTheDocument();
    expect(within(aeDecisions).queryByText("DM decision")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "DM feedback decisions" })).not.toBeInTheDocument();
  });

  it("accepts an assigned variable without a raw source", () => {
    const approve = vi.fn();
    const assigned = structuredClone(variable);
    assigned.datasets[0].variables.push({ name: "STUDYID", label: "Study Identifier", data_type: "Char", source_dataset: null, source_field: null, origin: "Assigned", mapping_expression: "Assign the approved study identifier SYN-101.", controlled_terms: [], value_level_metadata: [], crf_source_label: null });
    render(<SDTMVariableMappingReview value={{ source_spec: source, domain_mapping: domain, variable_mapping: assigned }} onChange={vi.fn()} onApprove={approve} saving={false} />);

    expect(screen.getByDisplayValue("No raw source — assigned/derived")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Approve mappings and generate rules/code"));
    expect(approve).toHaveBeenCalledWith(expect.objectContaining({
      datasets: [expect.objectContaining({ domain: "DM", variables: assigned.datasets[0].variables })],
    }));
  });

  it("allows a source to be reviewed as intentionally not mapped", () => {
    const approve = vi.fn();
    const onChange = vi.fn();
    const sourceWithOperationalData = {
      ...source,
      datasets: [...source.datasets, { name: "AUDIT_LOG", label: "Operational audit log", source_type: "raw" }],
    };
    const { rerender } = render(<SDTMDomainMappingReview value={{ source_spec: sourceWithOperationalData, domain_mapping: domain }} onChange={onChange} onApprove={approve} saving={false} />);

    expect(screen.getByRole("button", { name: "Approve domains and build variable mapping" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Mark AUDIT_LOG not mapped" }));
    const changed = onChange.mock.calls[0][0];
    rerender(<SDTMDomainMappingReview value={changed} onChange={onChange} onApprove={approve} saving={false} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Reason AUDIT_LOG is not mapped" }), { target: { value: "Operational metadata is outside SDTM tabulation scope." } });
    const reviewed = onChange.mock.calls[1][0];
    rerender(<SDTMDomainMappingReview value={reviewed} onChange={onChange} onApprove={approve} saving={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve domains and build variable mapping" }));

    expect(approve).toHaveBeenCalledWith(expect.objectContaining({
      unmapped_datasets: [{ source_dataset: "AUDIT_LOG", rationale: "Operational metadata is outside SDTM tabulation scope." }],
    }));
  });

  it("shows each feedback decision inside its respective domain tab", () => {
    const sourceWithAe = { ...source, datasets: [...source.datasets, { name: "RAW_AE", label: "Adverse events", source_type: "raw" }] };
    const domainWithAe = { ...domain, domain_mappings: [...domain.domain_mappings, { source_dataset: "RAW_AE", source_type: "raw", target_domain: "AE", relationship: "direct", rationale: "AE source" }] };
    const variableWithAe = structuredClone(variable);
    variableWithAe.datasets.push({ domain: "AE", description: "Adverse Events", structure: "One record per event", key_variables: ["USUBJID", "AESEQ"], variables: [{ name: "AETERM", label: "Reported Term", data_type: "Char", source_dataset: "RAW_AE", source_field: "AETERM", origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null }] });
    const result = { source_spec: sourceWithAe, domain_mapping: domainWithAe, variable_mapping: variableWithAe };
    const reviewJob = {
      id: "job-domain-feedback", workflow: "sdtm", status: "review_required", review_stage: "variable_mapping",
      result, result_revision: "b".repeat(64),
      review_patch: {
        transaction_id: "patch-domains", status: "proposed", stage: "variable_mapping", message: "Revise both domains.",
        scope: { paths: [], source_datasets: [], target_domains: ["DM", "AE"], variables: [] },
        baseline_revision: "a".repeat(64), proposed_revision: "c".repeat(64), conflicts: [],
        submitted_at: "2026-10-31T12:00:00Z", decided_at: null, reviewer: null,
        operations: [
          { path: "/variable_mapping/datasets/domain=DM/variables/name=AGE/mapping_expression", before: "Direct", after: "AGE" },
          { path: "/variable_mapping/datasets/domain=AE/variables/name=AETERM/mapping_expression", before: "Direct", after: "trim(AETERM)" },
        ],
      },
    } as Job;
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={reviewJob.id}><SDTMVariableMappingReview value={result} onChange={vi.fn()} onApprove={vi.fn()} saving={false} reviewJob={reviewJob} /></ReviewDraftProvider></QueryClientProvider>);

    expect(screen.getByRole("region", { name: "DM feedback decision" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "AE feedback decision" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /AE\s*1/ }));
    expect(screen.getByRole("region", { name: "AE feedback decision" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "DM feedback decision" })).not.toBeInTheDocument();
  });
});
