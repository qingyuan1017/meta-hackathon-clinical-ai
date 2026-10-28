# EDC source normalization

Normalize the deterministically extracted JSON or XLSX content into one complete `EDCSourceSpecification` for human review before SDTM mapping begins.

Identify the physical or logical source datasets that programming will map, then capture each source variable's identifier, label, type, length, format, required flag, codelist, form/question linkage, and exact file/sheet/row provenance when the extraction supplies it. Preserve existing-SDTM sources as `source_type: sdtm`; otherwise use `raw`.

Do not map anything to an SDTM target in this step. Do not invent missing datasets, variables, keys, codelists, or provenance. Use `unknown`, null, empty collections, assumptions, and `unresolved_items` where the source is incomplete or ambiguous. The submitted schema is an editable intake draft and must be approved by a user before downstream mapping agents can use it.
