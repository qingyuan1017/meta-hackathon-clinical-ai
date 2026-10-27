---
name: clinical-document-generation
description: Draft and revise supported clinical documents from a synthetic study brief or protocol through the Clinical AI Workbench. Use for protocol, SAP, CSR shell, consent, data-management, review, risk, deviation, and amendment drafts.
---

# Clinical Document Generation

Call `workbench_get_use_case` with `clinical-document` before execution so the current schema and formats remain authoritative.

- Use `workbench_submit_text_job` for text inputs and include `document_type` and any `study_brief` in options. Require explicit synthetic/de-identified acknowledgement.
- Use the REST upload endpoint or web UI for binary references.
- Poll with `workbench_get_job` and review assumptions, unresolved items, internal consistency, and missing source facts.
- Do not fabricate study results, patient information, signatures, approvals, or regulatory acceptance.
- Apply user-directed revisions through `workbench_update_job_result`. The API validates the complete structured document and rebuilds DOCX/PDF/JSON files deterministically.

Keep draft and expert-review warnings intact.
