from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schemas.reviews import ReviewPatchOperation, ReviewScope


VARIABLE_FIELDS = {
    "name", "label", "data_type", "mapping_type", "sources", "origin",
    "mapping_expression", "controlled_terms", "value_level_metadata", "crf_source_label", "acrf_annotations",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def result_revision(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_patch_request(*, stage: str, message: str, scope: ReviewScope, baseline: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "transaction_id": str(uuid4()),
        "status": "generating",
        "stage": stage,
        "message": message,
        "scope": scope.model_dump(mode="json"),
        "baseline_revision": result_revision(baseline),
        "submitted_at": now,
    }


def validate_scope(stage: str, scope: ReviewScope, current: dict[str, Any]) -> None:
    if not any((scope.paths, scope.source_datasets, scope.target_domains, scope.variables)):
        raise ValueError("Choose at least one path, source dataset, target domain, or variable for this revision.")
    for path in scope.paths:
        _get_pointer(current, path)
    if stage == "domain_mapping":
        available_sources = {
            str(item.get("name", "")).upper()
            for item in _records(current.get("source_spec", {}).get("datasets"))
        }
        unknown = sorted(set(scope.source_datasets) - available_sources)
        if unknown:
            raise ValueError(f"Review scope references unknown source datasets: {', '.join(unknown)}.")
        if not scope.source_datasets and not scope.paths:
            raise ValueError("Domain-mapping feedback must select at least one source dataset or JSON path.")
    if stage == "variable_mapping":
        datasets = {
            str(item.get("domain", "")).upper(): item
            for item in _records(current.get("variable_mapping", {}).get("datasets"))
        }
        requested_domains = set(scope.target_domains) | {item.domain for item in scope.variables}
        unknown_domains = sorted(requested_domains - set(datasets))
        if unknown_domains:
            raise ValueError(f"Review scope references unknown target domains: {', '.join(unknown_domains)}.")
        for item in scope.variables:
            names = {str(variable.get("name", "")).upper() for variable in _records(datasets[item.domain].get("variables"))}
            if item.variable not in names:
                raise ValueError(f"Review scope references unknown variable {item.domain}.{item.variable}.")
            unknown_fields = sorted(set(item.fields) - VARIABLE_FIELDS)
            if unknown_fields:
                raise ValueError(
                    f"Review scope references unsupported fields for {item.domain}.{item.variable}: "
                    f"{', '.join(unknown_fields)}."
                )
        if not requested_domains and not scope.paths:
            raise ValueError("Variable-mapping feedback must select a target domain, variable, or JSON path.")


def propose_scope(stage: str, message: str, current: dict[str, Any]) -> tuple[ReviewScope, list[str], str]:
    words = {token.upper() for token in re.findall(r"[A-Za-z0-9_]+", message)}
    matched: list[str] = []
    if stage == "domain_mapping":
        sources = [
            str(item.get("name", "")).upper()
            for item in _records(current.get("source_spec", {}).get("datasets"))
        ]
        selected = [source for source in sources if source in words]
        matched.extend(selected)
        return (
            ReviewScope(source_datasets=selected),
            matched,
            "Matched source dataset names in the comment." if selected else "No source dataset name was found; select the affected source before generating a revision.",
        )
    if stage == "variable_mapping":
        datasets = _records(current.get("variable_mapping", {}).get("datasets"))
        domains = [str(item.get("domain", "")).upper() for item in datasets]
        selected_domains = [domain for domain in domains if domain in words]
        variables = []
        for dataset in datasets:
            domain = str(dataset.get("domain", "")).upper()
            for variable in _records(dataset.get("variables")):
                name = str(variable.get("name", "")).upper()
                if name in words and (not selected_domains or domain in selected_domains):
                    variables.append({"domain": domain, "variable": name})
                    matched.append(f"{domain}.{name}")
        matched.extend(item for item in selected_domains if item not in matched)
        scope = ReviewScope(target_domains=[] if variables else selected_domains, variables=variables)
        explanation = (
            "Matched target-domain and variable names in the comment."
            if matched else
            "No SDTM domain or variable name was found; select the affected mapping before generating a revision."
        )
        return scope, matched, explanation

    top_level = [key for key in current if key.replace("_", " ").upper() in message.upper() or key.upper() in words]
    paths = [f"/{_escape_pointer(key)}" for key in top_level]
    return (
        ReviewScope(paths=paths),
        top_level,
        "Matched top-level draft sections in the comment." if paths else "No draft section was found; select at least one JSON path before generating a revision.",
    )


def scope_candidate(stage: str, baseline: dict[str, Any], raw_candidate: dict[str, Any], scope: ReviewScope) -> dict[str, Any]:
    proposed = copy.deepcopy(baseline)
    for path in scope.paths:
        proposed = _set_pointer(proposed, path, copy.deepcopy(_get_pointer(raw_candidate, path)))
    if stage == "domain_mapping" and scope.source_datasets:
        _merge_domain_mapping(proposed, raw_candidate, set(scope.source_datasets))
    if stage == "variable_mapping" and (scope.target_domains or scope.variables):
        _merge_variable_mapping(proposed, raw_candidate, scope)
    return proposed


def build_patch_record(request: dict[str, Any], baseline: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    operations = [item.model_dump(mode="json") for item in diff_operations(baseline, proposed)]
    if not operations:
        raise ValueError("The scoped revision did not propose any change to the selected mapping paths.")
    return {
        **request,
        "status": "proposed",
        "proposed_revision": result_revision(proposed),
        "operations": operations,
        "conflicts": [],
        "baseline": baseline,
        "proposed": proposed,
    }


def public_patch(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in {"baseline", "proposed"}}


def write_patch_record(job_dir: Path, record: dict[str, Any]) -> Path:
    directory = job_dir / "reviews" / str(record["transaction_id"])
    directory.mkdir(parents=True, exist_ok=True)
    status = str(record.get("status", "event"))
    path = directory / f"{status}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return path


def load_patch_record(job_dir: Path, transaction_id: str, status: str = "proposed") -> dict[str, Any]:
    path = job_dir / "reviews" / transaction_id / f"{status}.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("The saved review patch is invalid.")
    return loaded


def diff_operations(before: Any, after: Any, path: str = "") -> list[ReviewPatchOperation]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        operations: list[ReviewPatchOperation] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{_escape_pointer(str(key))}"
            if key not in before:
                operations.append(ReviewPatchOperation(path=child, before=None, after=after[key]))
            elif key not in after:
                operations.append(ReviewPatchOperation(path=child, before=before[key], after=None))
            else:
                operations.extend(diff_operations(before[key], after[key], child))
        return operations
    if isinstance(before, list) and isinstance(after, list):
        identity = _list_identity(before, after)
        if identity:
            before_map = {str(item[identity]).upper(): item for item in before}
            after_map = {str(item[identity]).upper(): item for item in after}
            operations = []
            for key in sorted(set(before_map) | set(after_map)):
                child = f"{path}/{identity}={_escape_pointer(key)}"
                operations.extend(diff_operations(before_map.get(key), after_map.get(key), child))
            return operations
    return [ReviewPatchOperation(path=path or "/", before=before, after=after)]


def three_way_merge(base: Any, current: Any, proposed: Any, path: str = "") -> tuple[Any, list[str]]:
    if proposed == base:
        return copy.deepcopy(current), []
    if current == base or current == proposed:
        return copy.deepcopy(proposed), []
    if isinstance(base, dict) and isinstance(current, dict) and isinstance(proposed, dict):
        result: dict[str, Any] = {}
        conflicts: list[str] = []
        for key in set(base) | set(current) | set(proposed):
            marker = object()
            base_value = base.get(key, marker)
            current_value = current.get(key, marker)
            proposed_value = proposed.get(key, marker)
            child = f"{path}/{_escape_pointer(str(key))}"
            if marker in (base_value, current_value, proposed_value):
                if proposed_value is marker and current_value == base_value:
                    continue
                if current_value is marker and proposed_value != base_value:
                    result[key] = copy.deepcopy(proposed_value)
                    continue
                if proposed_value == base_value:
                    result[key] = copy.deepcopy(current_value)
                    continue
                conflicts.append(child)
                if current_value is not marker:
                    result[key] = copy.deepcopy(current_value)
                continue
            merged, child_conflicts = three_way_merge(base_value, current_value, proposed_value, child)
            result[key] = merged
            conflicts.extend(child_conflicts)
        return result, conflicts
    if isinstance(base, list) and isinstance(current, list) and isinstance(proposed, list):
        identity = _list_identity(base, current, proposed)
        if identity:
            return _merge_keyed_lists(base, current, proposed, identity, path)
    return copy.deepcopy(current), [path or "/"]


def _merge_domain_mapping(proposed: dict[str, Any], raw: dict[str, Any], selected: set[str]) -> None:
    base_plan = proposed["domain_mapping"]
    raw_plan = raw["domain_mapping"]
    for key in ("domain_mappings", "unmapped_datasets"):
        kept = [item for item in _records(base_plan.get(key)) if str(item.get("source_dataset", "")).upper() not in selected]
        replacements = [item for item in _records(raw_plan.get(key)) if str(item.get("source_dataset", "")).upper() in selected]
        base_plan[key] = [*kept, *copy.deepcopy(replacements)]
    disposed = {
        str(item.get("source_dataset", "")).upper()
        for key in ("domain_mappings", "unmapped_datasets")
        for item in _records(raw_plan.get(key))
    }
    missing = sorted(selected - disposed)
    if missing:
        raise ValueError(f"The scoped domain revision omitted dispositions for: {', '.join(missing)}.")


def _merge_variable_mapping(proposed: dict[str, Any], raw: dict[str, Any], scope: ReviewScope) -> None:
    base_plan = proposed["variable_mapping"]
    raw_plan = raw["variable_mapping"]
    base_datasets = {str(item.get("domain", "")).upper(): item for item in _records(base_plan.get("datasets"))}
    raw_datasets = {str(item.get("domain", "")).upper(): item for item in _records(raw_plan.get("datasets"))}
    variable_scopes: dict[str, list[Any]] = {}
    for item in scope.variables:
        variable_scopes.setdefault(item.domain, []).append(item)
    full_domains = set(scope.target_domains) - set(variable_scopes)
    for domain in full_domains:
        if domain not in raw_datasets:
            raise ValueError(f"The scoped variable revision omitted target domain {domain}.")
        base_datasets[domain] = copy.deepcopy(raw_datasets[domain])
    for domain, selections in variable_scopes.items():
        if domain not in raw_datasets or domain not in base_datasets:
            raise ValueError(f"The scoped variable revision omitted target domain {domain}.")
        base_dataset = base_datasets[domain]
        raw_variables = {str(item.get("name", "")).upper(): item for item in _records(raw_datasets[domain].get("variables"))}
        base_variables = _records(base_dataset.get("variables"))
        positions = {str(item.get("name", "")).upper(): index for index, item in enumerate(base_variables)}
        for selection in selections:
            if selection.variable not in raw_variables:
                raise ValueError(f"The scoped revision omitted variable {domain}.{selection.variable}.")
            index = positions[selection.variable]
            candidate = raw_variables[selection.variable]
            if selection.fields:
                for field in selection.fields:
                    base_variables[index][field] = copy.deepcopy(candidate.get(field))
            else:
                base_variables[index] = copy.deepcopy(candidate)
        base_dataset["variables"] = base_variables
    order = [str(item.get("domain", "")).upper() for item in _records(base_plan.get("datasets"))]
    base_plan["datasets"] = [base_datasets[domain] for domain in order]


def _merge_keyed_lists(base: list[Any], current: list[Any], proposed: list[Any], identity: str, path: str) -> tuple[list[Any], list[str]]:
    base_map = {str(item[identity]).upper(): item for item in base}
    current_map = {str(item[identity]).upper(): item for item in current}
    proposed_map = {str(item[identity]).upper(): item for item in proposed}
    result: list[Any] = []
    conflicts: list[str] = []
    order = [str(item[identity]).upper() for item in current]
    order.extend(key for key in proposed_map if key not in order)
    for key in order:
        if key not in base_map:
            if key in current_map and key in proposed_map and current_map[key] != proposed_map[key]:
                conflicts.append(f"{path}/{identity}={_escape_pointer(key)}")
            result.append(copy.deepcopy(current_map.get(key, proposed_map.get(key))))
            continue
        if key not in current_map or key not in proposed_map:
            if key not in proposed_map and current_map.get(key) == base_map[key]:
                continue
            if key not in current_map and proposed_map.get(key) == base_map[key]:
                continue
            conflicts.append(f"{path}/{identity}={_escape_pointer(key)}")
            if key in current_map:
                result.append(copy.deepcopy(current_map[key]))
            continue
        merged, child_conflicts = three_way_merge(
            base_map[key], current_map[key], proposed_map[key], f"{path}/{identity}={_escape_pointer(key)}"
        )
        result.append(merged)
        conflicts.extend(child_conflicts)
    return result, conflicts


def _list_identity(*values: list[Any]) -> str | None:
    items = [item for value in values for item in value]
    if not items or not all(isinstance(item, dict) for item in items):
        return None
    for key in ("domain", "name", "source_dataset", "output_id", "rule_id", "variable", "finding_id", "where_clause"):
        if all(key in item and item[key] not in (None, "") for item in items):
            for value in values:
                keys = [str(item[key]).upper() for item in value]
                if len(keys) != len(set(keys)):
                    break
            else:
                return key
    return None


def _get_pointer(value: Any, pointer: str) -> Any:
    if pointer == "/":
        return value
    current = value
    for token in pointer.lstrip("/").split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list):
            index = _list_pointer_index(current, key, pointer)
            current = current[index]
        else:
            raise ValueError(f"Review scope path does not exist in the current draft: {pointer}.")
    return current


def _set_pointer(value: Any, pointer: str, replacement: Any) -> Any:
    if pointer == "/":
        return replacement
    current = value
    tokens = pointer.lstrip("/").split("/")
    for raw in tokens[:-1]:
        key = raw.replace("~1", "/").replace("~0", "~")
        current = current[_list_pointer_index(current, key, pointer)] if isinstance(current, list) else current[key]
    key = tokens[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(current, list):
        current[_list_pointer_index(current, key, pointer)] = replacement
    else:
        current[key] = replacement
    return value


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _list_pointer_index(value: list[Any], token: str, pointer: str) -> int:
    if token.isdigit() and int(token) < len(value):
        return int(token)
    if "=" in token:
        identity, expected = token.split("=", 1)
        matches = [
            index
            for index, item in enumerate(value)
            if isinstance(item, dict) and str(item.get(identity, "")).casefold() == expected.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
    raise ValueError(f"Review scope path does not exist or is ambiguous in the current draft: {pointer}.")


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
