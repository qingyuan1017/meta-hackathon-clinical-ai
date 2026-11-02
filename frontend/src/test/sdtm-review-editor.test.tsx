import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SDTMReviewEditor } from "@/components/sdtm-review-editor";
import { api } from "@/lib/api";
import type { Artifact, Job } from "@/lib/types";
import { ReviewDraftProvider, useReviewDraft } from "@/lib/review-draft-context";

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

function RevisionContextProbe() {
  const { sdtmRevisionContext } = useReviewDraft();
  return <output aria-label="SDTM revision context">{JSON.stringify(sdtmRevisionContext)}</output>;
}

describe("SDTMReviewEditor", () => {
  const renderEditor = (value = plan, jobId?: string, artifacts: Artifact[] = []) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(<QueryClientProvider client={client}><SDTMReviewEditor jobId={jobId} value={value} artifacts={artifacts} onChange={vi.fn()} onSave={vi.fn()} saving={false} /></QueryClientProvider>);
  };

  afterEach(() => vi.restoreAllMocks());

  it("presents actual syntax-highlighted domain programs plus separate aCRF and Define-XML review tabs", async () => {
    vi.spyOn(api, "artifactText").mockImplementation(async (path) => path.includes("sas") ? "data dm;\n  set raw_dm;\nrun;" : "# Build DM\ndm <- raw_dm");
    const artifacts: Artifact[] = [
      { id: "dm-r", name: "build-dm.R", media_type: "text/x-r-source", size_bytes: 25, sha256: "a".repeat(64), download_url: "/artifact/dm-r" },
      { id: "dm-sas", name: "build-dm.sas", media_type: "text/x-sas", size_bytes: 30, sha256: "b".repeat(64), download_url: "/artifact/dm-sas" },
    ];
    renderEditor(plan, undefined, artifacts);

    expect(screen.getByText("Domain mapping")).toBeInTheDocument();
    const reviewActions = screen.getByRole("group", { name: "SDTM review status and actions" });
    const saveMappings = within(reviewActions).getByRole("button", { name: "Save reviewed mappings" });
    expect(document.getElementById(saveMappings.getAttribute("aria-describedby")!)).toHaveTextContent("rebuild every generated artifact");
    expect(screen.getAllByRole("button", { name: "Save reviewed mappings" })).toHaveLength(1);
    expect(screen.getAllByText("RAW_DM")).toHaveLength(2);
    fireEvent.click(screen.getByText("Variable & VLM"));
    expect(screen.getByText("Use the variable-by-source matrix to edit target metadata, minor derivations, detailed lineage, and VLM rows.")).toBeInTheDocument();
    expect(screen.queryByText("Record construction pipeline")).not.toBeInTheDocument();
    expect(screen.getByText("Variable & VLM mapping matrix")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit AGE mapping" }));
    expect(screen.getAllByDisplayValue("AGE")).toHaveLength(2);
    expect(screen.getByRole("dialog", { name: "Edit AGE" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close variable mapping dialog" }));
    fireEvent.click(screen.getByText("Rule & code"));
    const rProgram = await screen.findByLabelText("DM R program");
    expect(rProgram).toHaveTextContent("# Build DM");
    expect(rProgram.querySelector('[data-token="comment"]')).toHaveTextContent("# Build DM");
    fireEvent.click(screen.getByRole("tab", { name: "SAS" }));
    const sasProgram = await screen.findByLabelText("DM SAS program");
    expect(sasProgram).toHaveTextContent("data dm;");
    expect(sasProgram.querySelector('[data-token="keyword"]')).toHaveTextContent("data");
    expect(screen.queryByText("Record construction pipeline")).not.toBeInTheDocument();
    expect(screen.queryByText("DM.AGE")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("aCRF review"));
    expect(screen.getByText("No aCRF was generated because this job did not include a blank CRF PDF. Start a new generation with a blank CRF to enable annotation review.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Define-XML"));
    expect(screen.getByText("Define-XML 2.1 review will appear after the SDTM artifacts are generated.")).toBeInTheDocument();
  });

  it("keeps completed-job agent guidance out of the workspace editor", async () => {
    renderEditor(plan, "job-1");

    expect(screen.queryByLabelText(/agent guidance/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Variable & VLM"));
    expect(screen.queryByRole("button", { name: /Rerun DM Variable/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Rule & code"));
    expect(screen.getByText("Generated R/SAS program artifacts are unavailable for DM. Save or rerun the reviewed mapping to build them.")).toBeInTheDocument();
    expect(screen.getByText(/use the right-side agent when you want a review-gated mapping or rule revision/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rerun DM rules/i })).not.toBeInTheDocument();
  });

  it("allows a reviewed domain program to be manually edited and saved", async () => {
    vi.spyOn(api, "artifactText").mockResolvedValue("# Build DM\ndm <- raw_dm");
    const update = vi.spyOn(api, "updateSdtmProgram").mockResolvedValue({} as Job);
    const artifacts: Artifact[] = [
      { id: "dm-r", name: "build-dm.R", media_type: "text/x-r-source", size_bytes: 25, sha256: "a".repeat(64), download_url: "/artifact/dm-r" },
    ];
    renderEditor(plan, "job-edit", artifacts);

    fireEvent.click(screen.getByText("Rule & code"));
    await screen.findByLabelText("DM R program");
    fireEvent.click(screen.getByRole("button", { name: "Edit R" }));
    const editor = screen.getByLabelText("DM R code editor");
    const syntax = screen.getByTestId("DM R code editor syntax highlighting");
    expect(syntax.querySelector('[data-token="comment"]')).toHaveTextContent("# Build DM");
    expect(screen.getByText(/marks prior execution and validation results as historical/i)).toBeInTheDocument();
    fireEvent.change(editor, { target: { value: "# Reviewed DM\ndm <- raw_dm |> dplyr::mutate(AGE = as.numeric(AGE))" } });
    expect(syntax.querySelector('[data-token="function"]')).toHaveTextContent("mutate");
    fireEvent.click(screen.getByRole("button", { name: "Save R" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(
      "job-edit",
      "DM",
      "r",
      "# Reviewed DM\ndm <- raw_dm |> dplyr::mutate(AGE = as.numeric(AGE))",
      "a".repeat(64),
    ));
  });

  it("makes the failed execution attempt selected for the right-side Rule & Code agent", async () => {
    vi.spyOn(api, "sdtmExecutions").mockResolvedValue({ items: [{
      attempt_id: "attempt-abcdef123456", parent_attempt_id: null, status: "failed",
      created_at: "2026-11-01T12:00:00Z", completed_at: "2026-11-01T12:01:00Z",
      program_hash: "c".repeat(64), runtime: { r: "4.4.1" }, exit_code: 1,
      stdout: "", stderr: "object 'AGE' not found", outputs: [],
      checks: [
        { check_id: "domain-execution", status: "failed", message: "DM R program failed independently with exit 1.", domain: "DM" },
        { check_id: "r-exit", status: "failed", message: "R exited with status 1", domain: "DM" },
      ],
      failure_classification: "runtime_error", repair_proposal: null,
    }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId="job-execution"><SDTMReviewEditor jobId="job-execution" value={plan} onChange={vi.fn()} onSave={vi.fn()} saving={false} /><RevisionContextProbe /></ReviewDraftProvider></QueryClientProvider>);

    fireEvent.click(screen.getByText("Execution"));

    const evidence = await screen.findByRole("radio", { name: /Use as Rule & Code evidence/i });
    expect(evidence).toBeChecked();
    expect(screen.getByText(/Selected evidence:/i)).toHaveTextContent("attempt-abcdef123456");
    expect(screen.getByText("Independent domain execution")).toBeInTheDocument();
    expect(screen.getByText("DM · failed")).toBeInTheDocument();
    expect(screen.getByText(/guidance, voice input, and scope in the right-side agent/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("SDTM revision context")).toHaveTextContent("Rule & Code repair · DM · attempt-abcdef123456"));
    expect(screen.getByLabelText("SDTM revision context")).toHaveTextContent('"executionAttemptId":"attempt-abcdef123456"');
  });

  it("previews a produced execution dataset on demand", async () => {
    vi.spyOn(api, "sdtmExecutions").mockResolvedValue({ items: [{
      attempt_id: "attempt-abcdef123456", parent_attempt_id: null, status: "passed",
      created_at: "2026-11-01T12:00:00Z", completed_at: "2026-11-01T12:01:00Z",
      program_hash: "c".repeat(64), runtime: { r: "4.4.1" }, exit_code: 0,
      stdout: "", stderr: "",
      outputs: [{ name: "dm.xpt", sha256: "d".repeat(64), size_bytes: 2048, row_count: 2, columns: ["USUBJID", "AGE"] }],
      checks: [{ check_id: "xpt-readable", status: "passed", message: "dm.xpt is readable with 2 rows.", domain: "DM" }],
      failure_classification: null, repair_proposal: null,
    }] });
    const preview = vi.spyOn(api, "sdtmExecutionOutputPreview").mockResolvedValue({
      name: "dm.xpt", row_count: 2, columns: ["USUBJID", "AGE"],
      rows: [{ USUBJID: "SYN-001", AGE: 42 }, { USUBJID: "SYN-002", AGE: null }],
      preview_limit: 25, truncated: false,
    });
    renderEditor(plan, "job-preview");

    fireEvent.click(screen.getByText("Execution"));
    const previewButton = await screen.findByRole("button", { name: "Preview result" });
    expect(preview).not.toHaveBeenCalled();
    fireEvent.click(previewButton);

    expect(await screen.findByRole("columnheader", { name: "USUBJID" })).toBeInTheDocument();
    expect(screen.getByText("SYN-001")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2 rows. Preview is read-only.")).toBeInTheDocument();
    expect(preview).toHaveBeenCalledWith("job-preview", "attempt-abcdef123456", "dm.xpt");
  });

  it("uses the full stage-review presentation for completed-job proposals", () => {
    const proposalPlan = structuredClone(plan) as typeof plan & { datasets: Array<(typeof plan.datasets)[number] & { review_assumptions: string[]; review_unresolved_mappings: string[] }> };
    proposalPlan.datasets[0].review_assumptions = ["DM.AGE remains numeric after source conversion."];
    proposalPlan.datasets[0].review_unresolved_mappings = [];
    proposalPlan.assumptions = ["DM.AGE remains numeric after source conversion."];
    const reviewJob = {
      id: "job-proposal", workflow: "sdtm", title: "Completed revision", status: "review_required", review_stage: "variable_mapping_domain",
      result: proposalPlan, result_revision: "a".repeat(64), review_patch: {
        transaction_id: "patch-1", status: "proposed", stage: "variable_mapping_domain", message: "Revise DM.AGE.",
        scope: { paths: [], source_datasets: [], target_domains: [], variables: [{ domain: "DM", variable: "AGE", fields: ["mapping_expression"] }] },
        baseline_revision: "a".repeat(64), proposed_revision: "b".repeat(64), conflicts: [], submitted_at: "2026-11-01T12:00:00Z", decided_at: null, reviewer: null,
        operations: [{ path: "/datasets/domain=DM/variables/name=AGE/mapping_expression", before: "Direct", after: "as.numeric(.data[[\"AGE\"]])" }],
      }, warnings: [], artifacts: [], error: null, created_at: "2026-11-01T12:00:00Z", updated_at: "2026-11-01T12:00:00Z", completed_at: null, sdtm_workbench: null,
    } as Job;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={reviewJob.id}><SDTMReviewEditor jobId={reviewJob.id} value={proposalPlan} onChange={vi.fn()} onSave={vi.fn()} saving={false} reviewJob={reviewJob} initialStage="variables" /></ReviewDraftProvider></QueryClientProvider>);

    expect(screen.getByText("Variable & VLM mapping matrix")).toBeInTheDocument();
    expect(screen.getByText(/Proposed overlay · 1 changes/i)).toBeInTheDocument();
    expect(screen.getByText("DM assumptions")).toBeInTheDocument();
    expect(screen.getByLabelText("DM feedback decision")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save reviewed mappings" })).not.toBeInTheDocument();
  });

  it("supports domain filtering, multiple annotations, domain styling, custom text, and click-to-edit", async () => {
    const editablePlan = structuredClone(plan);
    editablePlan.datasets[0].variables.push({
      name: "SEX", label: "Sex", data_type: "Char", mapping_type: "direct",
      sources: [{ dataset: "RAW_DM", variable: "SEX", role: "value" }], origin: "CRF",
      mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null,
    });
    editablePlan.rule_augmentations.push({ rule_id: "DM-SEX", target_domain: "DM", target_variable: "SEX", description: "Map SEX", logic: "Direct", r_expression: '.data[["SEX"]]', sas_expression: "SEX", review_notes: [] });
    editablePlan.domain_mappings.push({ source_dataset: "RAW_AE", source_type: "raw", target_domain: "AE", relationship: "direct", rationale: "Adverse events" });
    editablePlan.datasets.push({ domain: "AE", description: "Adverse events", structure: "One record per event", key_variables: ["USUBJID", "AESEQ"], record_plan: { steps: [{ step_id: "read_ae", operation: "read", description: "Read AE", output: "ae_source", inputs: [], source_dataset: "RAW_AE" }], output_step: "read_ae" }, variables: [{ name: "AETERM", label: "Term", data_type: "Char", mapping_type: "direct", sources: [{ dataset: "RAW_AE", variable: "AETERM", role: "value" }], origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null }] });
    editablePlan.rule_augmentations.push({ rule_id: "AE-AETERM", target_domain: "AE", target_variable: "AETERM", description: "Map AETERM", logic: "Direct", r_expression: '.data[["AETERM"]]', sas_expression: "AETERM", review_notes: [] });
    const artifacts: Artifact[] = [
      { id: "acrf-pdf", name: "annotated-crf.pdf", media_type: "application/pdf", size_bytes: 500, sha256: "c".repeat(64), download_url: "/artifact/acrf-pdf" },
      { id: "acrf-json", name: "acrf-annotations.json", media_type: "application/json", size_bytes: 200, sha256: "d".repeat(64), download_url: "/artifact/acrf-json" },
    ];
    vi.spyOn(api, "artifactText").mockResolvedValue(JSON.stringify({
      status: "review_required",
      pages: [{ page: 1, width: 612, height: 792 }, { page: 2, width: 612, height: 792 }],
      domain_styles: {
        DM: { font_family: "Helvetica", font_size: 8, text_color: "#141F3D", fill_color: "#EBF2FF" },
        AE: { font_family: "Helvetica", font_size: 8, text_color: "#141F3D", fill_color: "#EBF2FF" },
      },
      annotations: [
        { annotation_type: "variable", annotation_id: "DM.AGE.0", domain: "DM", variable: "AGE", annotation_index: 0, status: "matched", page: 1, label: "Age", mapping_text: "DM.AGE", textbox: [370, 100, 430, 126] },
        { annotation_type: "domain", annotation_id: "domain:DM:1", domain: "DM", variable: "", annotation_index: 0, status: "matched", page: 1, label: "", mapping_text: "DM", textbox: [18, 18, 70, 42] },
      ],
    }));
    const onChange = vi.fn();
    const onSave = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    function Harness() {
      const [value, setValue] = useState<Record<string, unknown>>(editablePlan);
      return <SDTMReviewEditor value={value} artifacts={artifacts} onChange={(next) => { onChange(next); setValue(next); }} onSave={onSave} saving={false} />;
    }
    render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);

    fireEvent.click(screen.getByText("aCRF review"));
    expect(await screen.findByText("1 annotation in DM.")).toBeInTheDocument();
    expect(screen.getByText("DM.AGE")).toBeInTheDocument();
    expect(screen.queryByText("AE.AETERM")).not.toBeInTheDocument();

    const overlay = await screen.findByRole("button", { name: "Edit and move DM.AGE annotation 1" });
    fireEvent.click(overlay);
    await waitFor(() => expect(screen.getByLabelText("CRF question text for DM.AGE annotation 1")).toHaveFocus());
    const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 612, bottom: 792, width: 612, height: 792, toJSON: () => ({}) });
    fireEvent.pointerDown(overlay, { pointerId: 1, clientX: 380, clientY: 110 });
    fireEvent.pointerMove(overlay, { pointerId: 1, clientX: 430, clientY: 160 });
    fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 430, clientY: 160 });
    fireEvent.change(screen.getByLabelText("aCRF mapping text for DM.AGE annotation 1"), { target: { value: "AGE at baseline" } });

    fireEvent.change(screen.getByLabelText("Domain annotation text for DM"), { target: { value: "DEMOGRAPHICS" } });
    const freeCard = screen.getByText("No-domain annotations").closest("article")!;
    fireEvent.click(within(freeCard).getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("No-domain annotation text 1"), { target: { value: "NOT SUBMITTED - TEST" } });

    const ageCard = screen.getByText("DM.AGE").closest("article")!;
    fireEvent.click(within(ageCard).getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("CRF question text for DM.AGE annotation 2"), { target: { value: "Age at follow-up" } });
    fireEvent.change(screen.getByLabelText("aCRF mapping text for DM.AGE annotation 2"), { target: { value: "AGE follow-up" } });
    expect(screen.getByText("2 annotations in DM.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("aCRF font for DM"), { target: { value: "Times Bold" } });
    fireEvent.change(screen.getByLabelText("aCRF font size for DM"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("aCRF text color for DM"), { target: { value: "#aa1122" } });
    fireEvent.change(screen.getByLabelText("aCRF background color for DM"), { target: { value: "#ccddff" } });

    fireEvent.change(screen.getByLabelText("aCRF domain"), { target: { value: "AE" } });
    expect(screen.getByText("AE.AETERM")).toBeInTheDocument();
    expect(screen.queryByText("DM.AGE")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("aCRF domain"), { target: { value: "DM" } });

    fireEvent.click(screen.getByRole("button", { name: "Save & rebuild" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ acrf_free_annotations: [expect.objectContaining({ text: "NOT SUBMITTED - TEST", page: 1 })], datasets: expect.arrayContaining([expect.objectContaining({ domain: "DM", acrf_font_family: "Times Bold", acrf_font_size: 11, acrf_text_color: "#AA1122", acrf_fill_color: "#CCDDFF", acrf_domain_annotation: expect.objectContaining({ enabled: true, text: "DEMOGRAPHICS" }), variables: expect.arrayContaining([expect.objectContaining({ name: "AGE", acrf_annotations: [
      { source_label: "Age", mapping_text: "AGE at baseline", page: 1, x: 420, y: 150 },
      { source_label: "Age at follow-up", mapping_text: "AGE follow-up" },
    ] })]) })]) }));
    bounds.mockRestore();
  });
});
