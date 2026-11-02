import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultView, SubmissionPackageTree } from "@/components/result-view";
import { api } from "@/lib/api";
import { ReviewDraftProvider } from "@/lib/review-draft-context";
import type { Artifact, Job } from "@/lib/types";


describe("SubmissionPackageTree", () => {
  it("shows the five package folders, their files, and empty optional folders", () => {
    const artifact = {
      id: "package-1",
      name: "sdtm-submission-package.zip",
      media_type: "application/zip",
      size_bytes: 4096,
      sha256: "a".repeat(64),
      download_url: "/api/v1/jobs/job-1/artifacts/package-1",
      package_members: [
        { path: "data", size_bytes: 0, is_directory: true },
        { path: "define", size_bytes: 0, is_directory: true },
        { path: "raw", size_bytes: 0, is_directory: true },
        { path: "spec", size_bytes: 0, is_directory: true },
        { path: "program", size_bytes: 0, is_directory: true },
        { path: "data/dm.xpt", size_bytes: 1024, is_directory: false },
        { path: "define/define.xml", size_bytes: 2048, is_directory: false },
        { path: "spec/sdtm-mapping.xlsx", size_bytes: 3072, is_directory: false },
        { path: "program/build-dm.R", size_bytes: 512, is_directory: false },
        { path: "program/build-dm.sas", size_bytes: 512, is_directory: false },
        { path: "package-manifest.json", size_bytes: 400, is_directory: false },
      ],
    } as Artifact;

    render(<SubmissionPackageTree artifact={artifact} />);

    expect(screen.getByText("data/")).toBeInTheDocument();
    expect(screen.getByText("define/")).toBeInTheDocument();
    expect(screen.getByText("raw/")).toBeInTheDocument();
    expect(screen.getByText("spec/")).toBeInTheDocument();
    expect(screen.getByText("program/")).toBeInTheDocument();
    expect(screen.getByText("dm.xpt")).toBeInTheDocument();
    expect(screen.getByText("define.xml")).toBeInTheDocument();
    expect(screen.getByText("build-dm.R")).toBeInTheDocument();
    expect(screen.getByText(/package-manifest\.json/)).toBeInTheDocument();
    expect(screen.getByText("No files available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download package/i })).toHaveAttribute("href", "http://localhost:8000/api/v1/jobs/job-1/artifacts/package-1");
  });
});

describe("ResultView controls", () => {
  afterEach(() => vi.restoreAllMocks());

  it("places icon-only generation actions beside the result status with detailed tooltips", async () => {
    const job = {
      id: "job-sdtm-result",
      workflow: "sdtm",
      title: "SDTM generation",
      status: "succeeded",
      review_stage: null,
      result_revision: "a".repeat(64),
      review_patch: null,
      result: {
        study_name: "SYN-101", standard: "SDTMIG 3.4", define_standard: "Define-XML 2.1",
        domain_mappings: [{ source_dataset: "RAW_DM", source_type: "raw", target_domain: "DM", relationship: "direct", rationale: "Demographics" }],
        datasets: [{ domain: "DM", description: "Demographics", structure: "One record per subject", key_variables: ["USUBJID"], record_plan: { steps: [{ step_id: "read_dm", operation: "read", description: "Read DM", output: "dm_source", inputs: [], source_dataset: "RAW_DM" }], output_step: "read_dm" }, variables: [{ name: "USUBJID", label: "Unique Subject Identifier", data_type: "Char", mapping_type: "direct", sources: [{ dataset: "RAW_DM", variable: "USUBJID", role: "value" }], origin: "CRF", mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null }] }],
        rule_augmentations: [{ rule_id: "DM-USUBJID", target_domain: "DM", target_variable: "USUBJID", description: "Map subject identifier", logic: "Direct", r_expression: '.data[["USUBJID"]]', sas_expression: "USUBJID", review_notes: [] }],
        assumptions: [], unresolved_mappings: [],
      },
      error: null, warnings: [], artifacts: [],
      sdtm_workbench: {
        lifecycle: { program_generation: "completed", execution: "not_run", validation: "not_run", submission_readiness: "blocked" },
        inputs: { raw_datasets: [{ logical_name: "RAW_DM", format: "csv", row_count: 2, columns: [{ name: "USUBJID", data_type: "character" }], sha256: "b".repeat(64) }], blank_crf: "blank-crf.pdf", validation_report: null },
        limitations: [],
      },
      created_at: "2026-11-02T12:00:00Z", updated_at: "2026-11-02T12:01:00Z", completed_at: "2026-11-02T12:01:00Z",
    } as Job;
    vi.spyOn(api, "agentProgress").mockResolvedValue({} as never);
    const retry = vi.spyOn(api, "retryJob").mockResolvedValue({ ...job, status: "queued" });
    const onReset = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><ResultView job={job} onReset={onReset} /></ReviewDraftProvider></QueryClientProvider>);

    const controls = screen.getByRole("group", { name: "Generation result controls" });
    expect(within(controls).getByText("succeeded")).toBeInTheDocument();
    const newGeneration = within(controls).getByRole("button", { name: "New generation" });
    const retrySameInputs = within(controls).getByRole("button", { name: "Retry same inputs" });
    const deleteJob = within(controls).getByRole("button", { name: "Delete job permanently" });
    expect(document.getElementById(newGeneration.getAttribute("aria-describedby")!)).toHaveTextContent("separate generation");
    expect(document.getElementById(retrySameInputs.getAttribute("aria-describedby")!)).toHaveTextContent("earliest incomplete stage");
    expect(document.getElementById(deleteJob.getAttribute("aria-describedby")!)).toHaveTextContent("cannot be undone");
    expect(screen.getAllByRole("button", { name: "New generation" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Retry same inputs" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Delete job permanently" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("tab", { name: "preview" }));
    expect(screen.getByRole("heading", { name: "SDTM mapping overview" })).toBeInTheDocument();
    expect(screen.getByText("SYN-101")).toBeInTheDocument();
    expect(screen.getByText("SDTMIG 3.4")).toBeInTheDocument();
    expect(screen.getByText("Define-XML 2.1")).toBeInTheDocument();
    expect(screen.getByText("1 dataset")).toBeInTheDocument();
    expect(screen.getByText("2 known rows")).toBeInTheDocument();
    expect(screen.getByText("blank-crf.pdf")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Source-to-domain mapping graph" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Mapping relationship distribution" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Reviewed variables by SDTM domain" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View DM variable mappings" }));
    const variableLineage = screen.getByRole("region", { name: "DM variable-level mappings" });
    expect(within(variableLineage).getByText(/RAW_DM\.USUBJID/)).toBeInTheDocument();
    expect(within(variableLineage).getByText("DM.USUBJID")).toBeInTheDocument();
    expect(within(variableLineage).getByText("direct")).toBeInTheDocument();

    fireEvent.click(newGeneration);
    fireEvent.click(retrySameInputs);
    expect(onReset).toHaveBeenCalledOnce();
    await waitFor(() => expect(retry).toHaveBeenCalledWith(job.id));
  });
});
