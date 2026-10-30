---
name: clinical-tlf-artifacts
description: Generate and revise draft table, listing, and figure specifications, shells, and R/SAS scaffolds from a synthetic SAP/protocol and optional ADaM metadata through the Clinical AI Workbench.
---

# Clinical TLF Artifacts

Discover the `tlf` contract with `workbench_get_use_case` before submitting work.

- Submit synthetic/de-identified text with `workbench_submit_text_job`; use the REST/UI path for binary SAP, protocol, or XLSX metadata.
- Use CDISC Library MCP metadata only when it materially supports ADaM/CDISC interpretation, and retain exact version context.
- Review output identifiers, populations, columns, statistics, sources, footnotes, and programming notes against the SAP and ADaM metadata.
- TLF jobs pause three times: first after the output table of contents, then after detailed shell generation for every approved output, and finally after ADaM-linked programming augmentation. Each approved stage is fixed input to the next stage.
- Programming review must trace every scaffold to the approved ADaM dataset-variable schema before final artifacts are rendered.
- Preserve explicit TODO markers where analysis metadata is insufficient. Never execute generated R or SAS.
- Apply user-requested edits with `workbench_update_job_result`; the API validates the full TLF plan and rebuilds the DOCX/JSON/program artifacts without another model call.

Treat shells and programs as non-validated scaffolds for statistical-programming review.
