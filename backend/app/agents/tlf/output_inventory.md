# TLF stage 1 — output inventory

Build a reviewable table of contents that combines source-defined outputs with a conventional clinical-study TLF package.

First extract every table, listing, and figure explicitly supported by the submitted SAP or protocol. Mark these items `source_supported` and preserve stable identifiers, titles, sections, purposes, populations, and exact source-document references.

Then add `conventional_proposal` items to cover the usual package when the source does not provide a complete output inventory. Consider, as applicable:

- subject disposition and analysis populations;
- demographics and baseline characteristics;
- each primary and secondary efficacy analysis described by the source;
- overall adverse-event summary;
- treatment-emergent adverse events by system organ class and preferred term;
- serious adverse events and adverse events leading to discontinuation or death;
- clinically relevant laboratory, vital-sign, or other safety summaries when those data are described;
- participant-level listings for important safety events; and
- a useful efficacy figure when repeated visits or treatment estimates support one.

Do not present a conventional proposal as source-defined. Give it a clear purpose, set `basis` to `conventional_proposal`, prefix `source_reference` with `CONVENTIONAL PROPOSAL —`, and use explicit `TODO` wording for every population, endpoint, analysis decision, or required dataset not established by the source. Add those gaps to `unresolved_items`. Supplied ADaM metadata may establish which datasets and variables are available, but it does not by itself establish an analysis decision.

Use ordered, stable identifiers within output type (for example T-01, L-01, and F-01). Do not map detailed ADaM inputs, design display shells, or write program code in this stage.
