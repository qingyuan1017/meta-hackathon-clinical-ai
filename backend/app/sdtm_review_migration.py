from __future__ import annotations

import copy
import re
from typing import Any


def attach_legacy_batch_review_notes(
    result: dict[str, Any],
    *,
    assumption_counts: list[int],
    unresolved_counts: list[int],
) -> dict[str, Any]:
    """Attach preserved batch comments to their domains without changing comment text."""

    migrated = copy.deepcopy(result)
    variable_plan = migrated.get("variable_mapping")
    domain_plan = migrated.get("domain_mapping")
    if not isinstance(variable_plan, dict) or not isinstance(domain_plan, dict):
        raise ValueError("The result does not contain SDTM domain and variable mapping plans.")
    datasets = variable_plan.get("datasets")
    if not isinstance(datasets, list) or not all(isinstance(item, dict) for item in datasets):
        raise ValueError("The variable mapping does not contain a valid dataset list.")
    if len(datasets) != len(assumption_counts) or len(datasets) != len(unresolved_counts):
        raise ValueError("The preserved batch counts do not match the target-domain count.")
    domains = [str(item.get("domain", "")).upper() for item in datasets]
    if not all(domains) or len(domains) != len(set(domains)):
        raise ValueError("Target-domain identifiers must be present and unique.")
    sources_by_domain: dict[str, list[str]] = {domain: [] for domain in domains}
    for mapping in domain_plan.get("domain_mappings", []):
        if not isinstance(mapping, dict):
            continue
        target = str(mapping.get("target_domain", "")).upper()
        source = str(mapping.get("source_dataset", "")).upper()
        if target in sources_by_domain and source:
            sources_by_domain[target].append(source)

    assumptions = _string_list(variable_plan.get("assumptions"))
    unresolved = _string_list(variable_plan.get("unresolved_mappings"))
    assumption_batches = _partition_with_deduplication(
        assumptions,
        counts=assumption_counts,
        domains=domains,
        sources_by_domain=sources_by_domain,
    )
    unresolved_batches = _partition_with_deduplication(
        unresolved,
        counts=unresolved_counts,
        domains=domains,
        sources_by_domain=sources_by_domain,
    )
    for index, dataset in enumerate(datasets):
        dataset["review_assumptions"] = assumption_batches[index]
        dataset["review_unresolved_mappings"] = unresolved_batches[index]
    return migrated


def _partition_with_deduplication(
    notes: list[str],
    *,
    counts: list[int],
    domains: list[str],
    sources_by_domain: dict[str, list[str]],
) -> list[list[str]]:
    if sum(counts) < len(notes):
        raise ValueError("Preserved batch counts contain fewer comments than the combined plan.")
    batches: list[list[str]] = []
    cursor = 0
    for index, count in enumerate(counts):
        if index == len(counts) - 1:
            boundary = len(notes)
        else:
            expected = min(cursor + count, len(notes))
            remaining_missing = max(sum(counts[index + 1 :]) - (len(notes) - expected), 0)
            boundary = expected
            next_domain = domains[index + 1]
            lower = max(cursor, expected - remaining_missing)
            for candidate in range(lower, expected):
                if _strong_domain_match(notes[candidate], next_domain, sources_by_domain[next_domain]):
                    boundary = candidate
                    break
        batches.append(notes[cursor:boundary])
        cursor = boundary
    if cursor != len(notes):
        raise ValueError("The preserved comments could not be assigned to all domain batches.")
    return batches


def _strong_domain_match(note: str, domain: str, sources: list[str]) -> bool:
    escaped = re.escape(domain)
    # Domain identifiers in generated review notes are emitted as uppercase tokens.
    # Preserve case here so short domains such as CO and BE do not match ordinary
    # words after uppercasing (for example, "coded" or "be").
    if re.search(rf"(?<![A-Z0-9_]){escaped}(?![A-Z0-9_])", note):
        return True
    upper = note.upper()
    for source in sources:
        escaped_source = re.escape(source.upper())
        if re.search(rf"(?<![A-Z0-9_]){escaped_source}(?![A-Z0-9_])", upper):
            return True
    return any(
        re.search(pattern, upper)
        for pattern in (
            rf"\b(?:TARGET|DOMAIN)\s+{escaped}\b",
            rf"\b{escaped}\s+DOMAIN\b",
            rf"->\s*{escaped}\b",
            rf"\b{escaped}\.",
        )
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Review comments must be a list of strings.")
    return value
