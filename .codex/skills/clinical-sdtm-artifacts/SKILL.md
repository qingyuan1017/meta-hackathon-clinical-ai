---
name: clinical-sdtm-artifacts
description: Generate and revise draft SDTM mapping, Define-XML, annotated CRF, and R/SAS scaffolds using the Workbench and CDISC Library MCP services. Use for synthetic SDTM artifact work, not conformance certification.
---

# Clinical SDTM Artifacts

Use `workbench_get_use_case("sdtm")` as the current contract. This workflow requires EDC JSON/XLSX. A blank CRF PDF is optional: include it to generate and review an aCRF, or omit it for mapping, Define-XML, and R/SAS code generation without an aCRF. Submission normally uses the web UI or multipart REST API rather than the text-only MCP submission tool.

Before SDTM mapping, an intake agent normalizes the deterministically extracted JSON/XLSX into an `EDCSourceSpecification`. The job pauses in `review_required` until a user reviews dataset/variable identifiers, types, keys, codelists, form/question links, and file/sheet/row provenance and approves the complete source schema.

After intake approval, the SDTM workflow runs three ordered stages:

1. Domain mapping determines each raw or existing SDTM source-dataset to target-SDTM-domain relationship.
2. Variable mapping determines an ordered typed record-construction plan plus complete multi-source traceability for variables and value-level metadata; when a blank CRF is supplied, its CRF source labels drive the aCRF annotations.
3. Rule augmentation adds one implementation rule per target variable. Record preparation is not free-form model code: the backend compiles the approved read/stack/join/transpose/filter/deduplicate/aggregate plan deterministically into each domain program.

After the ordered specialists finish, the registered SDTM lead rereads the user-approved EDC source specification and any supplied blank CRF and reconciles all three drafts under `backend/app/agents/sdtm/mapping_policy.md`. Treat stage drafts as fallible observations; only the lead's complete, cross-stage-validated `SDTMPlan` proceeds to deterministic rendering.

- Query CDISC Library MCP tools for the exact SDTMIG product, domains, variables, and controlled terminology needed. Preserve returned version identifiers.
- Poll the workbench job, complete the EDC source review gate when requested, and then review all three mapping stages, source-to-target traceability, origins, keys, derivations, value-level metadata, unresolved mappings, Define-XML references, and rule-to-code consistency. Review aCRF annotations only when a blank CRF was supplied.
- In the web review editor, use the ordered Domain mapping, Variable & VLM, Rule augmentation, aCRF review, and Define-XML tabs. Use drag-and-drop for raw-to-SDTM or SDTM-to-SDTM domain mappings, import versioned CDISC dataset metadata when needed, review every record-pipeline operation and every variable/VLM source-reference card, and treat sponsor SUPP additions as editable draft metadata. The aCRF and Define-XML tabs are derived previews; revise their source metadata in the mapping tabs and rebuild.
- Generated R may run only through the isolated Workbench runner after raw datasets are supplied and a human initiates execution. Never execute SAS and never claim regulatory conformance.
- For user-approved mapping changes, send the complete revised structured result to `workbench_update_job_result`. The API revalidates and rebuilds mappings, Define-XML, optional aCRF, program scaffolds, manifest, and ZIP without another model call.

Keep SDTMIG 3.4 / Define-XML 2.1 outputs labeled as draft metadata.
