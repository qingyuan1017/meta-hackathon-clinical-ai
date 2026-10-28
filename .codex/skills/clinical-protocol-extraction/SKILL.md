---
name: clinical-protocol-extraction
description: Extract structured clinical study facts, ambiguities, and a CDISC USDM 4.0 JSON artifact gated by the complete published CDISC CORE ruleset using the Clinical AI Workbench.
---

# Clinical Protocol Extraction

Use the workbench MCP tools as the execution boundary; do not reproduce the backend prompt or invent a second extraction schema.

Before submitting or reviewing an extraction, read and apply the repository's [shared protocol extraction policy](../../../backend/app/agents/protocol_extraction/extraction_policy.md). The backend lead and perspective agents load this same file at runtime.

1. Call `workbench_get_use_case` with `protocol-extraction` and respect its current input contract and result schema.
2. Confirm the source is synthetic or de-identified before calling `workbench_submit_text_job`. For PDF or DOCX input, direct the user to the web UI or `POST /api/v1/jobs/protocol-extraction` because the text MCP tool does not transport binaries.
3. Let the Workbench run its protocol team: parallel specialists inspect design/endpoints, conduct/eligibility, and safety/ambiguities, then a lead agent rereads the source and reconciles one schema-valid result.
4. Poll with `workbench_get_job`. A successful job includes `usdm.json`, the official raw `core-report.json`, and the Workbench decision `core-conformance.json`. Describe the artifact as CORE-conformant only when the decision says `conformant: true`.
5. Treat a failed conformance gate as a real failure, not a warning. Review the attached CORE diagnostics; never waive a finding, technical skip, incomplete ruleset, or engine failure, and never invent protocol facts merely to make a rule pass.
6. If the user requests corrections to a successful result, edit the structured result and call `workbench_update_job_result`; the backend validates the schema, reruns the complete CORE gate, and replaces artifacts only if the revision still conforms.
