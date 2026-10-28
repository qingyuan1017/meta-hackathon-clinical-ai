---
name: clinical-sdtm-artifacts
description: Generate and revise draft SDTM mapping, Define-XML, annotated CRF, and R/SAS scaffolds using the Workbench and CDISC Library MCP services. Use for synthetic SDTM artifact work, not conformance certification.
---

# Clinical SDTM Artifacts

Use `workbench_get_use_case("sdtm")` as the current contract. This workflow requires a blank CRF PDF plus EDC JSON/XLSX, so submission normally uses the web UI or multipart REST API rather than the text-only MCP submission tool.

The SDTM workflow runs three ordered stages:

1. Domain mapping determines each raw or existing SDTM source-dataset to target-SDTM-domain relationship.
2. Variable mapping determines variable traceability and value-level metadata; its CRF source labels drive the aCRF annotations.
3. Rule augmentation adds one source-preparation rule per target domain and one implementation rule per target variable; its R and SAS expressions drive the final draft program artifacts.

- Query CDISC Library MCP tools for the exact SDTMIG product, domains, variables, and controlled terminology needed. Preserve returned version identifiers.
- Poll the workbench job and review all three stages, source-to-target traceability, origins, keys, derivations, value-level metadata, unresolved mappings, Define-XML references, aCRF annotations, and rule-to-code consistency.
- In the web review editor, use drag-and-drop for raw-to-SDTM or SDTM-to-SDTM domain mappings, import versioned CDISC dataset metadata when needed, review variable/VLM cells, and treat sponsor SUPP additions as editable draft metadata.
- Never execute generated R or SAS and never claim regulatory conformance.
- For user-approved mapping changes, send the complete revised structured result to `workbench_update_job_result`. The API revalidates and rebuilds mappings, Define-XML, aCRF, program scaffolds, manifest, and ZIP without another model call.

Keep SDTMIG 3.4 / Define-XML 2.1 outputs labeled as draft metadata.
