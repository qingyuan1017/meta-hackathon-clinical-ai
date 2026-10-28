# Shared clinical protocol extraction policy

This policy is the common source of truth for Codex-side review and every backend protocol-extraction agent.

## Evidence authority

- Treat the supplied protocol as the authoritative source for study-specific facts. Model-generated specialist drafts are fallible observations, not evidence.
- Include only facts supported by the protocol. Preserve material qualifiers, thresholds, timing windows, conditional language, and stated category labels.
- Never use convention, general clinical knowledge, or agreement among agents to fill a source gap. External references may clarify terminology but must not replace protocol-specific facts.

## Required coverage

Collect the supported facts for study identity, phase, indication, sponsor, design, arms, population, sample size, duration, objectives and endpoints, visits, eligibility criteria, assessments, and safety monitoring. A specialist may focus on a subset, but the reconciled result must consider every area.

The backend maps the reconciled summary into the official CDISC USDM 4.0 wrapper, validates the API structure, and runs the complete pinned CDISC CORE USDM 4.0 ruleset. Preserve exact protocol identifiers, sponsor, title, category wording, controlled terms, and relationship evidence because they can affect conformance. Facts that cannot be represented natively without inventing required controlled terms or relationships are preserved through USDM extension attributes; never fabricate those terms merely to make a CORE rule pass. If the source is insufficient, the conformance gate must fail and expose diagnostics.

## Uncertainty and reconciliation

- Keep absent scalar facts at the schema default and absent collections empty.
- Put contradictions, missing definitions, unresolved cross-references, and unclear applicability or timing in `ambiguities` with enough context for a reviewer to locate and decide them.
- When specialist drafts disagree, verify each claim against the protocol. Prefer the protocol; if it does not resolve the conflict, preserve the conflict as an ambiguity.
- Keep the final summary concise and internally consistent. Never convert an absent or ambiguous fact into a confident value.

CORE conformance covers the published executable rules only. Every output still requires qualified clinical and regulatory review.
