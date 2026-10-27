---
name: clinical-protocol-extraction
description: Extract structured clinical study facts and ambiguities from a synthetic or de-identified protocol using the Clinical AI Workbench. Use when a protocol must become an editable study summary and review artifacts.
---

# Clinical Protocol Extraction

Use the workbench MCP tools as the execution boundary; do not reproduce the backend prompt or invent a second extraction schema.

1. Call `workbench_get_use_case` with `protocol-extraction` and respect its current input contract and result schema.
2. Confirm the source is synthetic or de-identified before calling `workbench_submit_text_job`. For PDF or DOCX input, direct the user to the web UI or `POST /api/v1/jobs/protocol-extraction` because the text MCP tool does not transport binaries.
3. Poll with `workbench_get_job`. Review objectives, endpoints, eligibility, visits, safety monitoring, and ambiguities against the supplied source.
4. Preserve uncertainty. Never convert an ambiguity or absent fact into a confident value.
5. If the user requests corrections, edit the structured result and call `workbench_update_job_result`; this validates the schema and regenerates JSON/Markdown artifacts without another model call.

Treat every output as a non-validated draft requiring clinical review.
