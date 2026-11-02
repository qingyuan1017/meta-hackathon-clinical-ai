import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentTurnTimeline } from "@/components/agent-turn-timeline";
import type { AgentProgress } from "@/lib/types";

const progress: AgentProgress = {
  agent_id: "clinical-protocol-extraction-agent",
  workflow: "protocol-extraction",
  status: "running",
  model: "meta-test-model",
  turn: 3,
  max_turns: 20,
  stage: "Reconciliation",
  stage_index: 2,
  stage_count: 2,
  completed_stages: ["Perspective extraction"],
  total_source_chunks: 2,
  read_source_chunks: [1],
  started_at: "2026-10-30T12:00:00Z",
  updated_at: "2026-10-30T12:00:03Z",
  events: [
    {
      turn: 1,
      type: "tool",
      name: "read_source_chunk",
      stage: "Perspective extraction",
      ok: true,
      summary: "Read one bounded section of the submitted source material.",
      intent: "Review source chunk 1 so the draft is grounded in the submitted material.",
      input_summary: "Requested source chunk 1 of 2.",
      output_summary: "Reviewed source chunk 1; 1 chunk(s) remain.",
      input_details: { "Chunk requested": 1 },
      output_details: { Status: "Reviewed", "Chunks remaining": 1 },
      evidence: ["Submitted source · chunk 1 of 2"],
      duration_ms: 42,
      occurred_at: "2026-10-30T12:00:01Z",
    },
    {
      turn: 2,
      type: "tool",
      name: "submit_result",
      stage: "Perspective extraction",
      ok: false,
      error: "Read every source chunk before submission.",
      summary: "Submitted the structured draft for schema and cross-reference validation.",
      intent: "Validate the complete structured draft and finish the current workflow stage.",
      input_summary: "Submitted 4 top-level fields: study_title, objectives, endpoints, visits.",
      output_summary: "The request was not accepted; review the recorded error before the next turn.",
      input_details: { "Top-level fields": 4 },
      output_details: { Status: "Rejected", Reason: "Read every source chunk before submission." },
      evidence: ["Backend schema and cross-reference validators"],
      duration_ms: 7,
      occurred_at: "2026-10-30T12:00:02Z",
    },
  ],
};

describe("AgentTurnTimeline", () => {
  it("shows useful request and outcome details for every agent turn", () => {
    const { container } = render(<AgentTurnTimeline progress={progress} />);

    expect(screen.getByText("meta-test-model")).toBeInTheDocument();
    expect(screen.getByText(/Turn 1 · Perspective Extraction/i)).toBeInTheDocument();
    expect(screen.getByText("Requested source chunk 1 of 2.")).toBeInTheDocument();
    expect(screen.getByText("Reviewed source chunk 1; 1 chunk(s) remain.")).toBeInTheDocument();
    expect(screen.getAllByText("Purpose of this turn")).toHaveLength(2);
    expect(screen.getByText("Review source chunk 1 so the draft is grounded in the submitted material.")).toBeInTheDocument();
    expect(screen.getByText("Submitted source · chunk 1 of 2")).toBeInTheDocument();
    expect(screen.getAllByText("Structured action details")).toHaveLength(2);
    expect(screen.getByText("42 ms")).toBeInTheDocument();
    expect(screen.getByText(/Turn 2 · Perspective Extraction/i)).toBeInTheDocument();
    expect(screen.getByText("Needs retry")).toBeInTheDocument();
    expect(screen.getAllByText(/Read every source chunk before submission/)).toHaveLength(2);
    expect(screen.getByText(/private model reasoning are not copied into the trace/)).toBeInTheDocument();

    const turns = container.querySelectorAll('ol[aria-label="Agent turn details"] > li > details');
    expect(turns).toHaveLength(2);
    expect(turns[0]).not.toHaveAttribute("open");
    expect(turns[1]).toHaveAttribute("open");
  });

  it("uses a compact summary in the activity rail", () => {
    render(<AgentTurnTimeline progress={progress} compact />);

    expect(screen.getByRole("region", { name: "Agent execution summary" })).toBeInTheDocument();
    expect(screen.queryByText(/private model reasoning are not copied into the trace/)).not.toBeInTheDocument();
    expect(screen.queryByText("Turns used")).not.toBeInTheDocument();
  });

  it("distinguishes human review guidance from agent actions", () => {
    const withFeedback = {
      ...progress,
      events: [...progress.events, {
        turn: 3,
        type: "user_feedback",
        actor: "user",
        name: "review_feedback",
        stage: "Reconciliation",
        summary: "Use the Safety population for every adverse-event output.",
        occurred_at: "2026-10-30T12:00:03Z",
      }],
    } as AgentProgress;

    render(<AgentTurnTimeline progress={withFeedback} compact />);

    expect(screen.getByText("Your guidance")).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getAllByText("Use the Safety population for every adverse-event output.")).not.toHaveLength(0);
  });

  it("keeps unmatched current constraints out of agent history", () => {
    render(<AgentTurnTimeline
      progress={progress}
      result={{ unresolved_items: ["The endpoint definition still requires confirmation."] }}
    />);

    expect(screen.queryByText("Other current constraints")).not.toBeInTheDocument();
    expect(screen.queryByText("The endpoint definition still requires confirmation.")).not.toBeInTheDocument();
  });
});
