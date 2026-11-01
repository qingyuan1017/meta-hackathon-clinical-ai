# Shared SDTM mapping policy

This policy is the common source of truth for the SDTM lead and every ordered mapping specialist.

## Evidence authority

- Treat the supplied EDC specification, optional blank CRF, and optional study context as the authoritative sources for study-specific structure and collection labels.
- Treat specialist drafts as fallible observations, not evidence. Verify their claims against the supplied sources and versioned CDISC Library metadata.
- Never invent source datasets, source variables, CRF labels, collected values, derivations, or controlled terms. Record unsupported or conflicting work in `unresolved_mappings`.

## Ordered mapping contract

Before mapping begins, deterministically extracted EDC content is normalized into an `EDCSourceSpecification` and approved by a user. Only that approved source schema may supply dataset and variable identifiers to downstream stages.

1. Domain mapping relates every raw or existing-SDTM source dataset to a target SDTMIG 3.4 domain using explicit direct, stack, join, split, or derived relationships. Stack appends observations as rows; join adds columns by reviewed keys and cardinality. Never represent both as a generic merge.
2. Variable mapping preserves the approved domain plan, adds a typed ordered record-construction plan for every target, and adds target variables with multi-source lineage, origins, controlled-term context, and source-aware value-level metadata. It adds exact blank-CRF labels for aCRF annotations only when a blank CRF was supplied.
3. Rule augmentation preserves both mapping stages and adds one implementation rule per target domain-variable pair. The backend compiles the approved record plan and combines it with these reviewed R and SAS expressions to produce deterministic draft programs.

Later stages may flag an earlier decision as unresolved but must not silently replace it. The lead reconciler must verify cross-stage references and retain a complete audit trail from each target domain and variable back to its source.

## Standards and safety

- Use SDTMIG 3.4 and Define-XML 2.1 as labeled draft baselines and preserve exact CDISC Library product/version identifiers when consulted.
- Sponsor SUPP variables and value-level metadata are editable draft metadata and must remain distinguishable from authoritative CDISC content.
- Generated R and SAS expressions are review scaffolds. Never execute them and never claim CDISC or regulatory conformance.
