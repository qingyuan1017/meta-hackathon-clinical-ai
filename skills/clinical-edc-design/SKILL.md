---
name: clinical-edc-design
description: Design and revise an EDC specification from a synthetic or de-identified protocol using Workbench and CDISC Library MCP metadata. Use for visits, forms, fields, codelists, derivations, and edit checks.
---

# Clinical EDC Design

1. Discover the `edc-design` contract with `workbench_get_use_case`.
2. When terminology or standard metadata matters, query the CDISC Library MCP narrowly and record the product/version used. Do not copy licensed standards content into the skill or claim conformance.
3. Submit de-identified text with `workbench_submit_text_job`, or use the REST/UI upload flow for PDF or DOCX sources.
4. Review visit/form references, unique identifiers, data types, requiredness, codelist usage, derivations, and edit-check field references.
5. Use `workbench_update_job_result` for user-approved structured changes. The API rebuilds the JSON and XLSX build specification without another model call.

Do not add fields unsupported by the protocol merely because they are common in other studies.
