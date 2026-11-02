import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RevisionDecisionPanel } from "@/components/revision-decision-panel";
import { getFeedbackDecisionSequence, getRevisionDecision } from "@/lib/revision-decision";

const result = {
  study_name: "SYN-101",
  assumptions: ["The source dataset remains DM until domain mapping begins."],
  unresolved_items: [
    "Review feedback 'Change the mapping to AE' cannot be applied in this normalization stage.",
    "Review feedback 'Add a RACE variable' cannot be applied because RACE is absent from the supplied EDC.",
  ],
};

describe("RevisionDecisionPanel", () => {
  it("surfaces review decisions without presenting private reasoning", () => {
    render(<RevisionDecisionPanel result={result} />);

    expect(screen.getByRole("region", { name: "Feedback decisions" })).toBeInTheDocument();
    expect(screen.getByText(/Change the mapping to AE/)).toBeInTheDocument();
    expect(screen.getByText(/RACE is absent/)).toBeInTheDocument();
    expect(screen.getByText(/not private model reasoning/i)).toBeInTheDocument();
  });

  it("pairs each feedback with its decision in event order", () => {
    const events = [
      { type: "user_feedback", actor: "user", summary: "Change the mapping to AE" },
      { type: "tool", actor: "agent", summary: "Revised the draft" },
      { type: "user_feedback", actor: "user", summary: "Add a RACE variable" },
    ];
    const sequence = getFeedbackDecisionSequence(result, [], events);

    expect(sequence.entries.map((entry) => entry.feedback)).toEqual(["Change the mapping to AE", "Add a RACE variable"]);
    expect(sequence.entries[0].decisions[0]).toContain("normalization stage");
    expect(sequence.entries[1].decisions[0]).toContain("RACE is absent");
    expect(sequence.unmatched).toEqual([]);

    render(<RevisionDecisionPanel result={result} events={events} />);
    const feedback = screen.getAllByText("Your feedback");
    expect(feedback).toHaveLength(2);
  });

  it("collects nested stage decisions and removes duplicates", () => {
    const decision = getRevisionDecision({
      source_spec: result,
      domain_mapping: { assumptions: result.assumptions, unresolved_mappings: [result.unresolved_items[0]] },
    });

    expect(decision.unresolved).toHaveLength(2);
    expect(decision.assumptions).toEqual(result.assumptions);
  });

  it("can hide unrelated feedback in a domain-scoped decision panel", () => {
    render(<RevisionDecisionPanel
      result={{ unresolved_mappings: ["DM decision"] }}
      events={[{ type: "user_feedback", actor: "user", summary: "Revise AE" }]}
      title="DM feedback decisions"
      ariaLabel="DM feedback decisions"
      onlyMatchedFeedback
    />);

    const panel = screen.getByRole("region", { name: "DM feedback decisions" });
    expect(panel).toHaveTextContent("Other current constraints");
    expect(panel).toHaveTextContent("DM decision");
    expect(screen.queryByText("Revise AE")).not.toBeInTheDocument();
  });
});
