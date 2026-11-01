import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ReviewPatchPanel } from "@/components/review-patch-panel";
import { api } from "@/lib/api";
import { ReviewDraftProvider } from "@/lib/review-draft-context";
import type { Job } from "@/lib/types";

describe("ReviewPatchPanel", () => {
  it("previews exact paths and requires an explicit decision", async () => {
    const job = {
      id: "job-1", status: "review_required", result_revision: "b".repeat(64),
      result: { study_name: "SYN-101" },
      review_patch: {
        transaction_id: "patch-1", status: "proposed", stage: "variable_mapping", message: "Revise DM.AGE.",
        scope: { paths: [], source_datasets: [], target_domains: [], variables: [{ domain: "DM", variable: "AGE", fields: ["mapping_expression"] }] },
        baseline_revision: "a".repeat(64), proposed_revision: "c".repeat(64), conflicts: [],
        submitted_at: "2026-10-31T12:00:00Z", decided_at: null, reviewer: null,
        operations: [{ path: "/variable_mapping/datasets/domain=DM/variables/name=AGE/mapping_expression", before: "Direct", after: "as.numeric(AGE)" }],
      },
    } as Job;
    const decide = vi.spyOn(api, "decideReviewPatch").mockResolvedValue({ ...job, review_patch: null } as Job);
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><ReviewPatchPanel job={job} /></ReviewDraftProvider></QueryClientProvider>);
    expect(screen.getByText(/mapping_expression/)).toBeInTheDocument();
    expect(screen.getByText(/as\.numeric\(AGE\)/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "DM feedback decision" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept all domain sections" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith(job.id, "patch-1", true, "b".repeat(64), job.result));
  });

  it("separates feedback decisions by SDTM domain", () => {
    const job = {
      id: "job-2", status: "review_required", result_revision: "b".repeat(64), result: {},
      review_patch: {
        transaction_id: "patch-2", status: "proposed", stage: "variable_mapping", message: "Revise DM and AE.",
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
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><ReviewPatchPanel job={job} /></ReviewDraftProvider></QueryClientProvider>);
    expect(screen.getByRole("region", { name: "DM feedback decision" })).toHaveTextContent("AGE");
    expect(screen.getByRole("region", { name: "AE feedback decision" })).toHaveTextContent("AETERM");
  });

  it("shows completed rule reruns under their target domain", () => {
    const job = {
      id: "job-3", status: "review_required", result_revision: "b".repeat(64),
      result: { rule_augmentations: [{ rule_id: "AE-AETERM", target_domain: "AE", target_variable: "AETERM" }] },
      review_patch: {
        transaction_id: "patch-3", status: "proposed", stage: "rule_augmentation_domain", message: "Regenerate AE rules.",
        scope: { paths: [], source_datasets: [], target_domains: ["AE"], variables: [] },
        baseline_revision: "a".repeat(64), proposed_revision: "c".repeat(64), conflicts: [],
        submitted_at: "2026-10-31T12:00:00Z", decided_at: null, reviewer: null,
        operations: [{ path: "/rule_augmentations/rule_id=AE-AETERM/logic", before: "Direct", after: "Normalize term" }],
      },
    } as Job;
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><ReviewPatchPanel job={job} /></ReviewDraftProvider></QueryClientProvider>);
    expect(screen.getByRole("region", { name: "AE feedback decision" })).toHaveTextContent("Normalize term");
    expect(screen.getByRole("button", { name: "Approve rerun and rebuild" })).toBeInTheDocument();
  });
});
