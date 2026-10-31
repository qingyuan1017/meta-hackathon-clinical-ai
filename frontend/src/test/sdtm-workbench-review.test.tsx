import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SDTMReviewEditor } from "@/components/sdtm-review-editor";
import { api } from "@/lib/api";

const plan = {
  study_name: "SYN-101", standard: "SDTMIG 3.4", define_standard: "Define-XML 2.1",
  domain_mappings: [{ source_dataset: "RAW_DM", source_type: "raw", target_domain: "DM", relationship: "direct", rationale: "Synthetic" }],
  datasets: [{ domain: "DM", description: "Demographics", structure: "One record per subject", key_variables: ["USUBJID"], record_plan: { steps: [{ step_id: "read_dm", operation: "read", description: "Read", output: "dm_source", inputs: [], source_dataset: "RAW_DM" }], output_step: "read_dm" }, variables: [{ name: "USUBJID", label: "Subject", data_type: "Char", mapping_type: "direct", sources: [{ dataset: "RAW_DM", variable: "USUBJID", role: "value" }], origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null }] }],
  rule_augmentations: [{ rule_id: "DM-USUBJID", target_domain: "DM", target_variable: "USUBJID", description: "Direct", logic: "Direct", r_expression: '.data[["USUBJID"]]', sas_expression: "USUBJID", review_notes: [] }], assumptions: [], unresolved_mappings: [],
};

const artifact = (id: string, name: string) => ({ id, name, media_type: "application/json", size_bytes: 10, sha256: "a".repeat(64), download_url: `/artifact/${id}` });
const workbench = { lifecycle: { program_generation: "completed", execution: "not_run", validation: "completed_with_findings", submission_readiness: "review_required" }, inputs: { raw_datasets: [], blank_crf: null, validation_report: null }, limitations: [] };

function renderEditor(artifacts: ReturnType<typeof artifact>[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><SDTMReviewEditor jobId="job-1" workbench={workbench} value={plan} artifacts={artifacts} onChange={vi.fn()} onSave={vi.fn()} saving={false} /></QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

describe("SDTM completed-job evidence review", () => {
  it("switches Define styled, exact raw, and diagnostics views", async () => {
    vi.spyOn(api, "artifactText").mockImplementation(async (path) => path.includes("diag") ? '{"well_formed":true,"xsd_validation":"not_run"}' : "<ODM exact=\"true\" />");
    renderEditor([artifact("xml", "define.xml"), artifact("html", "define.html"), artifact("diag", "define-diagnostics.json")]);
    fireEvent.click(screen.getByText("Define-XML"));
    expect(screen.getByTitle("Styled Define-XML review")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /raw/i }));
    expect(await screen.findByText('<ODM exact="true" />')).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /diagnostics/i }));
    expect(await screen.findByText(/xsd_validation/)).toBeInTheDocument();
  });

  it("triages a finding and requires an explicit approval choice", async () => {
    vi.spyOn(api, "validations").mockResolvedValue([{ validation_id: "val-1", provider: "Pinnacle 21 report import", provider_version: "3.1", status: "completed_with_findings", created_at: new Date().toISOString(), message: "Review required", diagnostics: null, findings: [{ finding_id: "f-1", provider: "Pinnacle 21 report import", provider_version: "3.1", rule_id: "SD0001", severity: "Warning", dataset: "DM", variable: "AGE", message: "Example finding", finding_status: "open", disposition: null, explanation: null, reviewer: null, approved_at: null }] }]);
    const update = vi.spyOn(api, "updateValidationFinding").mockResolvedValue({} as never);
    renderEditor();
    fireEvent.click(screen.getByText("Validation"));
    expect(await screen.findByText("Example finding")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("Open"), { target: { value: "explained" } });
    fireEvent.change(screen.getByPlaceholderText("Reviewer disposition/explanation"), { target: { value: "Approved synthetic explanation" } });
    fireEvent.click(screen.getByText("Approve explanation for cSDRG"));
    fireEvent.click(screen.getByText("Save disposition"));
    await waitFor(() => expect(update).toHaveBeenCalledWith("job-1", "f-1", expect.objectContaining({ approved: true, finding_status: "explained" })));
  });

  it("edits cSDRG JSON while the backend remains the evidence gate", async () => {
    const source = { study_name: "SYN-101", title: "Draft", sections: [], limitations: [], generated_at: new Date().toISOString() };
    vi.spyOn(api, "artifactText").mockResolvedValue(JSON.stringify(source, null, 2));
    const update = vi.spyOn(api, "updateCsdrg").mockResolvedValue(source);
    renderEditor([artifact("csdrg-json", "csdrg.json"), artifact("csdrg-pdf", "csdrg.pdf")]);
    fireEvent.click(screen.getByText("cSDRG"));
    const editor = await screen.findByLabelText("Editable cSDRG JSON");
    await waitFor(() => expect((editor as HTMLTextAreaElement).value).toContain('"title": "Draft"'));
    fireEvent.change(editor, { target: { value: JSON.stringify({ ...source, title: "Reviewed draft" }) } });
    fireEvent.click(screen.getByText("Save cSDRG review"));
    await waitFor(() => expect(update).toHaveBeenCalledWith("job-1", expect.objectContaining({ title: "Reviewed draft" })));
  });
});

