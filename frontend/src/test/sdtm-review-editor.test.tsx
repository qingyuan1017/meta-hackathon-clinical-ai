import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { SDTMReviewEditor } from "@/components/sdtm-review-editor";
import { api } from "@/lib/api";

const plan = {
  study_name: "SYN-101",
  standard: "SDTMIG 3.4",
  define_standard: "Define-XML 2.1",
  domain_mappings: [{ source_dataset: "RAW_DM", source_type: "raw", target_domain: "DM", relationship: "direct", rationale: "Demographics" }],
  datasets: [{ domain: "DM", description: "Demographics", structure: "One record per subject", key_variables: ["STUDYID", "USUBJID"], record_plan: { steps: [{ step_id: "read_dm", operation: "read", description: "Read DM", output: "dm_source", inputs: [], source_dataset: "RAW_DM" }], output_step: "read_dm" }, variables: [{ name: "AGE", label: "Age", data_type: "Num", mapping_type: "direct", sources: [{ dataset: "RAW_DM", variable: "AGE", role: "value" }], origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: "Age" }] }],
  rule_augmentations: [{ rule_id: "DM-AGE", target_domain: "DM", target_variable: "AGE", description: "Map AGE", logic: "Direct", r_expression: '.data[["AGE"]]', sas_expression: "AGE", review_notes: [] }],
  assumptions: [],
  unresolved_mappings: [],
};

describe("SDTMReviewEditor", () => {
  const renderEditor = (value = plan, jobId?: string) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(<QueryClientProvider client={client}><SDTMReviewEditor jobId={jobId} value={value} onChange={vi.fn()} onSave={vi.fn()} saving={false} /></QueryClientProvider>);
  };

  it("presents ordered mapping stages plus separate aCRF and Define-XML review tabs", () => {
    renderEditor();

    expect(screen.getByText("Domain mapping")).toBeInTheDocument();
    expect(screen.getAllByText("RAW_DM")).toHaveLength(2);
    fireEvent.click(screen.getByText("Variable & VLM"));
    expect(screen.getByText("Review the record pipeline first, then each variable and value-level lineage card.")).toBeInTheDocument();
    expect(screen.getByText("Record construction pipeline")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("AGE")).toHaveLength(2);
    fireEvent.click(screen.getByText("Rule augmentation"));
    expect(screen.getByText("DM.AGE")).toBeInTheDocument();
    fireEvent.click(screen.getByText("aCRF review"));
    expect(screen.getByText("No aCRF was generated because this job did not include a blank CRF PDF. Start a new generation with a blank CRF to enable annotation review.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Define-XML"));
    expect(screen.getByText("Define-XML 2.1 review will appear after the SDTM artifacts are generated.")).toBeInTheDocument();
  });

  it("offers independent completed-job reruns for the selected domain", async () => {
    const rerun = vi.spyOn(api, "rerunSdtmDomain").mockResolvedValue({} as never);
    renderEditor(plan, "job-1");

    fireEvent.click(screen.getByText("Variable & VLM"));
    fireEvent.click(screen.getByRole("button", { name: "Rerun DM Variable & VLM" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("job-1", "variable_mapping", "DM"));

    fireEvent.click(screen.getByText("Rule augmentation"));
    expect(screen.getByText("DM.AGE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rerun DM rules" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("job-1", "rule_augmentation", "DM"));
  });
});
