from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException

from .schemas import (
    EDCSourceCodeList,
    EDCSourceDataset,
    EDCSourceProvenance,
    EDCSourceSpecification,
    EDCSourceVariable,
)


_DATASET_COLLECTION_KEYS = ("datasets", "domains", "tables", "forms")
_VARIABLE_COLLECTION_KEYS = ("variables", "fields", "columns", "items", "questions")
_DATASET_NAME_KEYS = (
    "name",
    "dataset",
    "dataset_name",
    "datasetName",
    "domain",
    "domain_name",
    "domainName",
    "id",
    "form_id",
    "formId",
    "formName",
    "table",
    "table_name",
    "tableName",
    "schema",
    "schema_name",
    "schemaName",
)
_VARIABLE_NAME_KEYS = (
    "name",
    "variable",
    "variable_name",
    "variableName",
    "field",
    "field_name",
    "fieldName",
    "id",
    "field_id",
    "fieldId",
    "item_id",
    "itemId",
    "column",
    "column_name",
    "columnName",
)
_LABEL_KEYS = ("label", "description", "title", "question", "prompt")
_TYPE_KEYS = ("data_type", "datatype", "dataType", "type")
_CODELIST_COLLECTION_KEYS = ("codelists", "code_lists", "cts", "controlled_terms")


@dataclass(frozen=True)
class EDCJSONNormalization:
    specification: EDCSourceSpecification
    adapter: str
    dataset_paths: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _DatasetCandidate:
    value: dict[str, Any]
    path: str
    implied_name: str | None = None
    variable_key: str | None = None


def normalize_edc_json(path: Path) -> EDCJSONNormalization | None:
    """Build a complete, reviewable EDC source draft without an LLM.

    Recognized dataset/variable collections are traversed from the parsed JSON tree, so
    the result is not constrained by prompt chunk limits. ``None`` means the structure
    did not contain a supportable dataset/variable collection and may use the bounded
    agent fallback when the complete document fits that fallback.
    """

    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON in {path.name}: {exc.msg}") from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{path.name} is not valid UTF-8 JSON.") from exc

    candidates, adapter = _dataset_candidates(root)
    if not candidates:
        return None

    assumptions: list[str] = []
    unresolved: list[str] = []
    datasets: list[EDCSourceDataset] = []
    seen_datasets: set[str] = set()
    dataset_paths: list[str] = []

    for candidate in candidates:
        dataset = _normalize_dataset(
            candidate,
            filename=path.name,
            assumptions=assumptions,
            unresolved=unresolved,
        )
        if dataset is None:
            continue
        folded_name = dataset.name.casefold()
        if folded_name in seen_datasets:
            unresolved.append(
                f"Duplicate dataset identifier {dataset.name!r} at {candidate.path} was not imported; "
                "resolve the duplicate during source review."
            )
            continue
        seen_datasets.add(folded_name)
        datasets.append(dataset)
        dataset_paths.append(candidate.path)

    if not datasets:
        return None

    study_name = _study_name(root)
    if study_name is None:
        study_name = path.stem
        assumptions.append(
            f"Study name was unavailable in the JSON; the source filename stem {path.stem!r} was used."
        )

    codelists = _normalize_codelists(root, unresolved)
    known_codelists = {item.name.casefold() for item in codelists}
    for dataset in datasets:
        for variable in dataset.variables:
            if variable.codelist and variable.codelist.casefold() not in known_codelists:
                unresolved.append(
                    f"{dataset.name}.{variable.name} references codelist {variable.codelist!r}, but its "
                    "definition was not found in the JSON. An empty placeholder was retained for review."
                )
                codelists.append(EDCSourceCodeList(name=variable.codelist, values=[]))
                known_codelists.add(variable.codelist.casefold())

    warnings = (
        f"Deterministically normalized all {len(datasets)} discovered dataset(s) from {path.name} "
        f"using the {adapter} JSON adapter; human approval is still required.",
    )
    specification = EDCSourceSpecification(
        study_name=study_name,
        datasets=datasets,
        codelists=codelists,
        assumptions=_unique(assumptions),
        unresolved_items=_unique(unresolved),
    )
    return EDCJSONNormalization(
        specification=specification,
        adapter=adapter,
        dataset_paths=tuple(dataset_paths),
        warnings=warnings,
    )


def _dataset_candidates(root: Any) -> tuple[list[_DatasetCandidate], str]:
    if isinstance(root, dict):
        for key in _DATASET_COLLECTION_KEYS:
            actual = _matching_key(root, key)
            if actual is None:
                continue
            candidates = _candidates_from_collection(root[actual], _property_path("$", actual))
            if candidates:
                return candidates, f"root-{key}"

    discovered: list[_DatasetCandidate] = []
    seen_paths: set[str] = set()

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            variable_key = _candidate_variable_key(value)
            if variable_key is not None:
                if path not in seen_paths:
                    discovered.append(
                        _DatasetCandidate(value=value, path=path, variable_key=variable_key)
                    )
                    seen_paths.add(path)
                return
            for key, child in value.items():
                child_path = _property_path(path, str(key))
                if _key_matches(str(key), _DATASET_COLLECTION_KEYS):
                    for candidate in _candidates_from_collection(child, child_path):
                        if candidate.path not in seen_paths:
                            discovered.append(candidate)
                            seen_paths.add(candidate.path)
                else:
                    visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(root, "$")
    return discovered, "generic-recursive"


def _candidates_from_collection(value: Any, path: str) -> list[_DatasetCandidate]:
    if isinstance(value, list):
        return [
            _DatasetCandidate(
                item,
                f"{path}[{index}]",
                variable_key=_candidate_variable_key(item),
            )
            for index, item in enumerate(value)
            if isinstance(item, dict) and _has_variable_collection(item)
        ]
    if isinstance(value, dict):
        return [
            _DatasetCandidate(
                item,
                _property_path(path, str(key)),
                implied_name=str(key),
                variable_key=_candidate_variable_key(item),
            )
            for key, item in value.items()
            if isinstance(item, dict) and _has_variable_collection(item)
        ]
    return []


def _normalize_dataset(
    candidate: _DatasetCandidate,
    *,
    filename: str,
    assumptions: list[str],
    unresolved: list[str],
) -> EDCSourceDataset | None:
    value = candidate.value
    variable_key = candidate.variable_key or _candidate_variable_key(value)
    if variable_key is None:
        return None
    variable_nodes = _named_nodes(value[variable_key], _property_path(candidate.path, variable_key))
    if not variable_nodes:
        unresolved.append(f"No named variables were found for the candidate dataset at {candidate.path}.")
        return None

    name = _string_from(value, _DATASET_NAME_KEYS) or candidate.implied_name
    if not name:
        unresolved.append(
            f"A dataset candidate at {candidate.path} had no identifier and was not imported."
        )
        return None
    name = name.strip()
    label = _string_from(value, _LABEL_KEYS)
    if not label:
        label = name
        assumptions.append("Missing dataset labels were represented by their source identifiers.")

    variables: list[EDCSourceVariable] = []
    seen_variables: set[str] = set()
    for node, node_path, implied_name in variable_nodes:
        variable = _normalize_variable(
            node,
            node_path=node_path,
            implied_name=implied_name,
            filename=filename,
            assumptions=assumptions,
            unresolved=unresolved,
            dataset_name=name,
        )
        if variable is None:
            continue
        folded_name = variable.name.casefold()
        if folded_name in seen_variables:
            unresolved.append(
                f"Duplicate variable identifier {name}.{variable.name} at {node_path} was not imported."
            )
            continue
        seen_variables.add(folded_name)
        variables.append(variable)
    if not variables:
        unresolved.append(f"Dataset {name!r} at {candidate.path} had no importable variables.")
        return None

    raw_keys = _value_from(value, ("key_variables", "keys", "keyVariables"))
    key_variables = _string_list(raw_keys)
    known_variables = {variable.name.casefold(): variable.name for variable in variables}
    supported_keys: list[str] = []
    for key in key_variables:
        canonical = known_variables.get(key.casefold())
        if canonical:
            supported_keys.append(canonical)
        else:
            unresolved.append(
                f"Dataset {name} declares key {key!r}, which does not match an imported variable."
            )

    source_type_raw = (_string_from(value, ("source_type", "sourceType")) or "").casefold()
    source_type = "sdtm" if source_type_raw == "sdtm" else "raw"
    if not source_type_raw:
        assumptions.append("Datasets without an explicit source type were treated as raw sources.")
    elif source_type_raw not in {"raw", "sdtm"}:
        unresolved.append(
            f"Dataset {name} has unsupported source type {source_type_raw!r}; it was represented as raw "
            "pending human review."
        )

    structure = _string_from(value, ("structure", "grain", "record_structure")) or "Not specified"
    if structure == "Not specified":
        assumptions.append("Dataset record structures not supplied by the source remain 'Not specified'.")

    return EDCSourceDataset(
        name=name,
        label=label,
        source_type=source_type,
        structure=structure,
        key_variables=_unique(supported_keys),
        variables=variables,
        provenance=EDCSourceProvenance(file=filename, json_path=candidate.path),
    )


def _normalize_variable(
    value: dict[str, Any],
    *,
    node_path: str,
    implied_name: str | None,
    filename: str,
    assumptions: list[str],
    unresolved: list[str],
    dataset_name: str,
) -> EDCSourceVariable | None:
    name = _string_from(value, _VARIABLE_NAME_KEYS) or implied_name
    if not name:
        unresolved.append(f"A variable at {node_path} had no identifier and was not imported.")
        return None
    name = name.strip()
    label = _string_from(value, _LABEL_KEYS)
    if not label:
        label = name
        assumptions.append("Missing variable labels were represented by their source identifiers.")

    raw_type = _string_from(value, _TYPE_KEYS)
    data_type = _data_type(raw_type)
    if raw_type is None:
        assumptions.append("Variables without a source datatype remain typed as 'unknown'.")
    elif data_type == "unknown":
        unresolved.append(
            f"Datatype {raw_type!r} for {dataset_name}.{name} at {node_path} was not recognized."
        )

    length = _positive_int(_value_from(value, ("length", "max_length", "maxLength", "size")))
    required = _bool_value(_value_from(value, ("required", "mandatory", "is_required", "isRequired")))
    if required is None:
        required = False
        assumptions.append("Variables without a required flag were represented as not required for review.")

    codelist_raw = _value_from(value, ("codelist", "code_list", "codeList", "controlled_terms"))
    codelist = _reference_name(codelist_raw)
    form_id = _string_from(value, ("form_id", "form", "formId"))
    question = _string_from(value, ("question", "prompt", "question_text", "questionText"))
    format_value = _string_from(value, ("format", "display_format", "displayFormat"))

    return EDCSourceVariable(
        name=name,
        label=label,
        data_type=data_type,
        length=length,
        format=format_value,
        required=required,
        codelist=codelist,
        form_id=form_id,
        question=question,
        provenance=EDCSourceProvenance(file=filename, json_path=node_path),
    )


def _normalize_codelists(root: Any, unresolved: list[str]) -> list[EDCSourceCodeList]:
    if not isinstance(root, dict):
        return []
    raw = _value_from(root, _CODELIST_COLLECTION_KEYS)
    if raw is None:
        return []
    if isinstance(raw, dict):
        nodes = []
        for key, value in raw.items():
            path = _property_path("$.codelists", str(key))
            if isinstance(value, dict):
                nodes.append((value, path, str(key)))
            elif isinstance(value, list):
                nodes.append(({"values": value}, path, str(key)))
    else:
        nodes = _named_nodes(raw, "$.codelists")
    result: list[EDCSourceCodeList] = []
    seen: set[str] = set()
    for value, path, implied_name in nodes:
        name = _string_from(value, ("name", "id", "codelist", "code")) or implied_name
        if not name:
            unresolved.append(f"A codelist at {path} had no identifier and was not imported.")
            continue
        values_raw = _value_from(value, ("values", "terms", "items", "codes"))
        values = _term_values(values_raw)
        folded = name.casefold()
        if folded in seen:
            unresolved.append(f"Duplicate codelist identifier {name!r} at {path} was not imported.")
            continue
        seen.add(folded)
        result.append(EDCSourceCodeList(name=name, values=values))
    return result


def _study_name(root: Any) -> str | None:
    if not isinstance(root, dict):
        return None
    value = _value_from(root, ("study_name", "studyName", "study", "protocol"))
    if isinstance(value, dict):
        return _string_from(value, ("name", "id", "title"))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _string_from(root, ("name", "title"))


def _named_nodes(value: Any, path: str) -> list[tuple[dict[str, Any], str, str | None]]:
    if isinstance(value, list):
        return [
            (item, f"{path}[{index}]", None)
            for index, item in enumerate(value)
            if isinstance(item, dict)
        ]
    if isinstance(value, dict):
        return [
            (item, _property_path(path, str(key)), str(key))
            for key, item in value.items()
            if isinstance(item, dict)
        ]
    return []


def _has_variable_collection(value: dict[str, Any]) -> bool:
    return _candidate_variable_key(value) is not None


def _candidate_variable_key(value: dict[str, Any]) -> str | None:
    key = _first_matching_key(value, _VARIABLE_COLLECTION_KEYS)
    if key is not None and _looks_like_variable_collection(value[key]):
        return key
    if _string_from(value, _DATASET_NAME_KEYS) is None:
        return None
    for candidate, child in value.items():
        nodes = _named_nodes(child, "$")
        if not nodes:
            continue
        if any(
            _string_from(node, _VARIABLE_NAME_KEYS) is not None
            and (
                _string_from(node, _TYPE_KEYS) is not None
                or _string_from(node, _LABEL_KEYS) is not None
            )
            for node, _, _ in nodes
        ):
            return str(candidate)
    return None


def _looks_like_variable_collection(value: Any) -> bool:
    nodes = _named_nodes(value, "$")
    if not nodes:
        return False
    return any(
        _string_from(node, _VARIABLE_NAME_KEYS) is not None or implied_name is not None
        for node, _, implied_name in nodes
    )


def _data_type(value: str | None) -> str:
    if value is None:
        return "unknown"
    normalized = value.strip().casefold().replace("_", " ").replace("-", " ")
    if normalized in {"char", "character", "string", "text", "varchar"}:
        return "text"
    if normalized in {"int", "integer", "whole number", "long", "short"}:
        return "integer"
    if normalized in {"num", "numeric", "number", "decimal", "float", "double", "real"}:
        return "decimal"
    if normalized in {"date"}:
        return "date"
    if normalized in {"datetime", "date time", "timestamp"}:
        return "datetime"
    if normalized in {"bool", "boolean", "yes/no", "yes no"}:
        return "boolean"
    if normalized in {"coded", "code", "enum", "enumeration", "choice", "select"}:
        return "coded"
    return "unknown"


def _term_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, (str, int, float, bool)):
            result.append(str(item))
        elif isinstance(item, dict):
            term = _string_from(item, ("value", "code", "name", "label", "term"))
            if term is not None:
                result.append(term)
    return _unique(result)


def _reference_name(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        return _string_from(value, ("name", "id", "code"))
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            name = _string_from(item, _VARIABLE_NAME_KEYS)
            if name:
                result.append(name)
    return _unique(result)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit() and int(value.strip()) > 0:
        return int(value.strip())
    return None


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "y", "required", "mandatory", "1"}:
            return True
        if normalized in {"false", "no", "n", "optional", "0"}:
            return False
    return None


def _string_from(value: dict[str, Any], keys: Iterable[str]) -> str | None:
    raw = _value_from(value, keys)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)
    return None


def _value_from(value: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        actual = _matching_key(value, key)
        if actual is not None:
            return value[actual]
    return None


def _first_matching_key(value: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        actual = _matching_key(value, key)
        if actual is not None:
            return actual
    return None


def _matching_key(value: dict[str, Any], key: str) -> str | None:
    folded = key.casefold()
    return next((candidate for candidate in value if str(candidate).casefold() == folded), None)


def _key_matches(value: str, keys: Iterable[str]) -> bool:
    folded = value.casefold()
    return any(folded == key.casefold() for key in keys)


def _property_path(parent: str, key: str) -> str:
    if key.replace("_", "a").isalnum() and not key[:1].isdigit():
        return f"{parent}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{parent}['{escaped}']"


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
