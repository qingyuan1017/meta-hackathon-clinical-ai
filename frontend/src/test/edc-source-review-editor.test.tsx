import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EDCSourceReviewEditor } from "@/components/edc-source-review-editor";

const sourceSpecification = {
  study_name: "SYN-101",
  datasets: [
    {
      name: "RAW_DM",
      label: "Demographics",
      source_type: "raw",
      structure: "One row per subject",
      key_variables: ["SUBJID"],
      variables: [
        {
          name: "SUBJID",
          label: "Subject identifier",
          data_type: "text",
          length: 20,
          format: null,
          required: true,
          codelist: null,
          form_id: "DM",
          question: "Subject Identifier",
          provenance: { file: "edc.xlsx", sheet: "Fields", row: 2 },
        },
      ],
      provenance: { file: "edc.xlsx", sheet: "Datasets", row: 2 },
    },
  ],
  codelists: [],
  assumptions: [],
  unresolved_items: [],
};

describe("EDCSourceReviewEditor", () => {
  it("presents normalized datasets for approval before SDTM mapping", () => {
    const approve = vi.fn();
    render(<EDCSourceReviewEditor value={sourceSpecification} onChange={vi.fn()} onApprove={approve} saving={false} />);

    expect(screen.getByText("EDC source review required")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("RAW_DM")).toHaveLength(1);
    expect(screen.getAllByDisplayValue("SUBJID")).toHaveLength(1);
    fireEvent.click(screen.getByText("Approve source and begin SDTM mapping"));
    expect(approve).toHaveBeenCalledOnce();
  });
});
