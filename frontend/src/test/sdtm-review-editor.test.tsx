import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SDTMReviewEditor } from "@/components/sdtm-review-editor";
import { api } from "@/lib/api";
import type { Artifact } from "@/lib/types";

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

  it("offers independent completed-job reruns for the selected domain", async () => {
    const rerun = vi.spyOn(api, "rerunSdtmDomain").mockResolvedValue({} as never);
    renderEditor(plan, "job-1");

    fireEvent.click(screen.getByText("Variable & VLM"));
    fireEvent.click(screen.getByRole("button", { name: "Rerun DM Variable & VLM" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("job-1", "variable_mapping", "DM"));

    fireEvent.click(screen.getByText("Rule & code"));
    expect(screen.getByText("Generated R/SAS program artifacts are unavailable for DM. Save or rerun the reviewed mapping to build them.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rerun DM rules/code" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("job-1", "rule_augmentation", "DM"));
  });

  it("supports reviewing, adding, editing, deleting, and rebuilding aCRF mappings", async () => {
    const editablePlan = structuredClone(plan);
    editablePlan.datasets[0].variables.push({
      name: "SEX", label: "Sex", data_type: "Char", mapping_type: "direct",
      sources: [{ dataset: "RAW_DM", variable: "SEX", role: "value" }], origin: "CRF",
      mapping_expression: "Direct", controlled_terms: [], value_level_metadata: [], crf_source_label: null,
    });
    editablePlan.rule_augmentations.push({ rule_id: "DM-SEX", target_domain: "DM", target_variable: "SEX", description: "Map SEX", logic: "Direct", r_expression: '.data[["SEX"]]', sas_expression: "SEX", review_notes: [] });
    const artifacts: Artifact[] = [
      { id: "acrf-pdf", name: "annotated-crf.pdf", media_type: "application/pdf", size_bytes: 500, sha256: "c".repeat(64), download_url: "/artifact/acrf-pdf" },
      { id: "acrf-json", name: "acrf-annotations.json", media_type: "application/json", size_bytes: 200, sha256: "d".repeat(64), download_url: "/artifact/acrf-json" },
    ];
    vi.spyOn(api, "artifactText").mockResolvedValue(JSON.stringify({
      status: "review_required",
      annotations: [
        { domain: "DM", variable: "AGE", status: "matched", page: 1, label: "Age", style: { font_family: "Helvetica", font_size: 8, text_color: "#141F3D", fill_color: "#EBF2FF" } },
        { domain: "DM", variable: "SEX", status: "unmatched", page: null, label: "", style: { font_family: "Helvetica", font_size: 8, text_color: "#141F3D", fill_color: "#EBF2FF" } },
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
    expect(await screen.findByText("1 of 2 target variables have question text.")).toBeInTheDocument();
    expect(screen.getByLabelText("CRF question text for DM.AGE")).toHaveValue("Age");

    fireEvent.change(screen.getByLabelText("CRF question text for DM.SEX"), { target: { value: "Sex" } });
    expect(screen.getByText("2 of 2 target variables have question text.")).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ datasets: [expect.objectContaining({ variables: expect.arrayContaining([expect.objectContaining({ name: "SEX", crf_source_label: "Sex" })]) })] }));

    fireEvent.change(screen.getByLabelText("aCRF font for DM.SEX"), { target: { value: "Times Bold" } });
    fireEvent.change(screen.getByLabelText("aCRF font size for DM.SEX"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("aCRF text color for DM.SEX"), { target: { value: "#aa1122" } });
    fireEvent.change(screen.getByLabelText("aCRF background color for DM.SEX"), { target: { value: "#ccddff" } });
    expect(screen.getByText("#AA1122")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("CRF question text for DM.AGE"), { target: { value: "Age at screening" } });
    expect(screen.getByLabelText("CRF question text for DM.AGE")).toHaveValue("Age at screening");
    fireEvent.click(screen.getByRole("button", { name: "Remove aCRF mapping for DM.AGE" }));
    expect(screen.getByLabelText("CRF question text for DM.AGE")).toHaveValue("");
    expect(screen.getByText("1 of 2 target variables have question text.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save & rebuild" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ datasets: [expect.objectContaining({ variables: expect.arrayContaining([
      expect.objectContaining({ name: "AGE", crf_source_label: null }),
      expect.objectContaining({ name: "SEX", crf_source_label: "Sex", acrf_font_family: "Times Bold", acrf_font_size: 11, acrf_text_color: "#AA1122", acrf_fill_color: "#CCDDFF" }),
    ]) })] }));
  });
});
