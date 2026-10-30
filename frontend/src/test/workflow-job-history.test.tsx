import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowJobHistory } from "@/components/workflow-job-history";
import { api } from "@/lib/api";
import type { Job, JobList } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: { jobs: vi.fn() },
}));

const job = {
  id: "job-1",
  workflow: "sdtm",
  title: "SDTM mapping draft",
  status: "succeeded",
  created_at: "2026-10-29T12:00:00Z",
  updated_at: "2026-10-29T12:05:00Z",
  completed_at: "2026-10-29T12:05:00Z",
  model_name: "test-model",
  result: null,
  error: null,
  warnings: [],
  artifacts: [],
  review_stage: null,
} as Job;

function renderHistory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkflowJobHistory workflow="sdtm" currentJobId="job-1" />
    </QueryClientProvider>,
  );
}

describe("WorkflowJobHistory", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads only the selected workflow and links jobs back to that module", async () => {
    vi.mocked(api.jobs).mockResolvedValue({ items: [job], total: 1, page: 1, page_size: 6 } as JobList);

    renderHistory();

    expect(await screen.findByText("SDTM mapping draft")).toBeInTheDocument();
    expect(api.jobs).toHaveBeenCalledWith("sdtm", 1, 6);
    expect(screen.getByRole("link", { name: /SDTM mapping draft/i })).toHaveAttribute(
      "href",
      "/workflows/sdtm?job=job-1",
    );
  });

  it("paginates within the module", async () => {
    vi.mocked(api.jobs).mockImplementation(async (_workflow, page) => ({
      items: [page === 2 ? { ...job, id: "job-7", title: "Older SDTM job" } : job],
      total: 7,
      page: page ?? 1,
      page_size: 6,
    } as JobList));

    renderHistory();
    await screen.findByText("SDTM mapping draft");
    fireEvent.click(screen.getByRole("button", { name: "Next jobs page" }));

    await waitFor(() => expect(api.jobs).toHaveBeenCalledWith("sdtm", 2, 6));
    expect(await screen.findByText("Older SDTM job")).toBeInTheDocument();
  });
});
