from __future__ import annotations


def normalize_languages(value: object) -> list[str]:
    if isinstance(value, list):
        selected = [str(item).lower() for item in value]
    elif isinstance(value, str):
        selected = [part.strip().lower() for part in value.split(",")]
    else:
        selected = ["r", "sas"]
    result = [item for item in selected if item in {"r", "sas"}]
    return result or ["r", "sas"]
