import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentActivitySidebar } from "@/components/agent-activity-sidebar";
import { api } from "@/lib/api";
import { convertRecordingToWav } from "@/lib/audio";
import type { AgentProgress, Job } from "@/lib/types";

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

vi.mock("@/lib/audio", () => ({
  convertRecordingToWav: vi.fn(async () => new Blob(["wav"], { type: "audio/wav" })),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
});

describe("AgentActivitySidebar", () => {
  it("submits human guidance as a stage revision without approval", async () => {
    vi.spyOn(api, "agentProgress").mockResolvedValue(progress);
    const submit = vi.spyOn(api, "submitReviewFeedback").mockResolvedValue({ ...job, status: "queued", review_stage: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><AgentActivitySidebar job={job} /></QueryClientProvider>);

    const inputs = await screen.findAllByLabelText("Review guidance for the agent");
    fireEvent.change(inputs[0], { target: { value: "Use the Safety population for every AE output." } });
    const buttons = screen.getAllByRole("button", { name: "Request revision" });
    fireEvent.click(buttons[0]);

    await waitFor(() => expect(submit).toHaveBeenCalledWith(job.id, "Use the Safety population for every AE output."));
    expect(screen.getAllByText(/does not approve or advance/i)).not.toHaveLength(0);
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
    render(<QueryClientProvider client={client}><AgentActivitySidebar job={job} /></QueryClientProvider>);

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
