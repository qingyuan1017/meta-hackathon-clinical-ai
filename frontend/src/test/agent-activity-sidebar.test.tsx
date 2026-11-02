import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentActivitySidebar } from "@/components/agent-activity-sidebar";
import { api } from "@/lib/api";
import { convertRecordingToWav } from "@/lib/audio";
import type { AgentProgress, Job } from "@/lib/types";
import { ReviewDraftProvider, useReviewDraft } from "@/lib/review-draft-context";

const job = {
  id: "job-review",
  workflow: "tlf",
  title: "TLF review",
  status: "review_required",
  review_stage: "tlf_shell",
  model_name: "test-model",
  created_at: "2026-10-30T12:00:00Z",
  updated_at: "2026-10-30T12:00:00Z",
  completed_at: null,
  result: { study_name: "SYN-101", outputs: [] },
  warnings: [],
  error: null,
  artifacts: [],
  result_revision: "a".repeat(64),
  review_patch: null,
} as Job;

const progress = {
  agent_id: "clinical-tlf-artifacts-agent",
  workflow: "tlf",
  status: "completed",
  model: "test-model",
  turn: 3,
  max_turns: 60,
  stage: "Analysis & display specification",
  stage_index: 2,
  stage_count: 3,
  completed_stages: ["Output inventory"],
  total_source_chunks: 1,
  read_source_chunks: [1],
  events: [],
} as AgentProgress;

const completedSdtmJob = {
  ...job,
  id: "job-sdtm-complete",
  workflow: "sdtm",
  status: "succeeded",
  review_stage: null,
  completed_at: "2026-10-30T13:00:00Z",
  result: { study_name: "SYN-101", datasets: [{ domain: "DM" }] },
} as Job;

function VariableSelection() {
  const { setSdtmRevisionContext } = useReviewDraft();
  useEffect(() => {
    setSdtmRevisionContext({ surface: "variable_mapping", label: "Variable & VLM · DM", domain: "DM" });
  }, [setSdtmRevisionContext]);
  return null;
}

function ExecutionSelection() {
  const { setSdtmRevisionContext } = useReviewDraft();
  useEffect(() => {
    setSdtmRevisionContext({
      surface: "execution",
      label: "Rule & Code repair · DM · attempt-abcdef123456",
      domain: "DM",
      executionAttemptId: "attempt-abcdef123456",
    });
  }, [setSdtmRevisionContext]);
  return null;
}

vi.mock("@/lib/audio", () => ({
  convertRecordingToWav: vi.fn(async () => new Blob(["wav"], { type: "audio/wav" })),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
});

describe("AgentActivitySidebar", () => {
  it("starts collapsed and supports docked and full-screen history views", async () => {
    vi.spyOn(api, "agentProgress").mockResolvedValue(progress);
    const onOpenChange = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><AgentActivitySidebar job={job} onOpenChange={onOpenChange} /></ReviewDraftProvider></QueryClientProvider>);

    expect(screen.queryByRole("dialog", { name: "Agent activity history" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Agent history" }));
    expect(screen.getByRole("complementary", { name: "Agent activity history" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Agent activity history" })).not.toBeInTheDocument();
    expect(onOpenChange).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole("button", { name: "View agent history full screen" }));
    expect(screen.getByRole("dialog", { name: "Agent activity history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exit full screen agent history" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Collapse agent history" }));
    expect(screen.queryByRole("dialog", { name: "Agent activity history" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Agent history" })).toBeInTheDocument();
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("submits human guidance as a stage revision without approval", async () => {
    vi.spyOn(api, "agentProgress").mockResolvedValue(progress);
    const submit = vi.spyOn(api, "submitReviewFeedback").mockResolvedValue({ ...job, status: "queued", review_stage: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><AgentActivitySidebar job={job} /></ReviewDraftProvider></QueryClientProvider>);

    fireEvent.click(screen.getByRole("button", { name: "Agent history" }));
    const inputs = await screen.findAllByLabelText("Review guidance for the agent");
    fireEvent.change(inputs[0], { target: { value: "Use the Safety population for every AE output." } });
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    const buttons = screen.getAllByRole("button", { name: "Generate patch" });
    fireEvent.click(buttons[0]);

    await waitFor(() => expect(submit).toHaveBeenCalledWith(job.id, expect.objectContaining({
      message: "Use the Safety population for every AE output.",
      baseline_revision: "a".repeat(64),
      current_result: job.result,
      scope: expect.objectContaining({ paths: ["/study_name"] }),
    })));
    expect(screen.getAllByText(/does not approve or advance/i)).not.toHaveLength(0);
  });

  it("uses the current completed SDTM selection for right-side agent revisions", async () => {
    vi.spyOn(api, "agentProgress").mockResolvedValue(progress);
    const rerun = vi.spyOn(api, "rerunSdtmDomain").mockResolvedValue({ ...completedSdtmJob, status: "queued" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={completedSdtmJob.id}><VariableSelection /><AgentActivitySidebar job={completedSdtmJob} /></ReviewDraftProvider></QueryClientProvider>);

    fireEvent.click(screen.getByRole("button", { name: "Agent history" }));
    expect(await screen.findByText("Variable & VLM · DM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start voice input" })).toBeInTheDocument();
    expect(screen.getByText("DM")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Review guidance for the agent"), { target: { value: "Use RFSTDTC when deriving DM.RFSTDTC." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(rerun).toHaveBeenCalledWith(completedSdtmJob.id, "variable_mapping", "DM", {
      guidance: "Variable/VLM revision: Use RFSTDTC when deriving DM.RFSTDTC.",
      executionAttemptId: undefined,
      scope: { paths: [], source_datasets: [], target_domains: ["DM"], variables: [] },
    }));
  });

  it("submits selected execution evidence through the existing Rule & Code agent composer", async () => {
    vi.spyOn(api, "agentProgress").mockResolvedValue(progress);
    const rerun = vi.spyOn(api, "rerunSdtmDomain").mockResolvedValue({ ...completedSdtmJob, status: "queued" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={completedSdtmJob.id}><ExecutionSelection /><AgentActivitySidebar job={completedSdtmJob} /></ReviewDraftProvider></QueryClientProvider>);

    fireEvent.click(screen.getByRole("button", { name: "Agent history" }));
    expect(await screen.findByText("Rule & Code repair · DM · attempt-abcdef123456")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start voice input" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Review guidance for the agent"), { target: { value: "Correct the missing AGE reference." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(rerun).toHaveBeenCalledWith(completedSdtmJob.id, "rule_augmentation", "DM", {
      guidance: "Execution-informed rule/code revision: Correct the missing AGE reference.",
      executionAttemptId: "attempt-abcdef123456",
      scope: { paths: [], source_datasets: [], target_domains: ["DM"], variables: [] },
    }));
  });

  it("records voice guidance and inserts the Meta transcript without submitting", async () => {
    const stopTrack = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
    });
    class FakeMediaRecorder {
      static isTypeSupported = () => true;
      state: RecordingState = "inactive";
      mimeType = "audio/webm";
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      onstop: (() => void) | null = null;
      constructor(_stream: MediaStream, _options?: MediaRecorderOptions) {}
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob(["voice"]) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.spyOn(api, "agentProgress").mockResolvedValue(progress);
    const transcribe = vi.spyOn(api, "transcribeReviewAudio").mockResolvedValue({
      transcript: "Use the Safety population.",
      model: "muse-voice-transcribe-1.0",
      duration_ms: 900,
      session_id: "voice-session",
    });
    const submit = vi.spyOn(api, "submitReviewFeedback");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewDraftProvider jobId={job.id}><AgentActivitySidebar job={job} /></ReviewDraftProvider></QueryClientProvider>);

    fireEvent.click(screen.getByRole("button", { name: "Agent history" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Start voice input" }))[0]);
    const stop = await screen.findByRole("button", { name: "Stop voice input" });
    fireEvent.click(stop);

    await waitFor(() => expect(transcribe).toHaveBeenCalledWith(job.id, expect.any(Blob)));
    await waitFor(() => expect(screen.getAllByLabelText("Review guidance for the agent")[0]).toHaveValue("Use the Safety population."));
    expect(convertRecordingToWav).toHaveBeenCalledWith(expect.any(Blob));
    expect(submit).not.toHaveBeenCalled();
    expect(stopTrack).toHaveBeenCalled();
  });
});
