from __future__ import annotations

import re


_FORBIDDEN_WORDS = re.compile(r"\b(?:data|if|proc|quit|run|set|where)\b", re.I)
_NARRATIVE_WORDS = re.compile(r"\b(?:indicates?|confirmed?|reviewed?|occurred)\b", re.I)


def normalize_sas_filter_expression(value: str) -> str:
    """Return one conservative SAS boolean expression suitable for an IF statement."""

    expression = value.strip()
    if not expression:
        raise ValueError("SAS filter expression is empty.")
    if "\n" in expression or "\r" in expression:
        raise ValueError("SAS filter expression must be a single line.")

    masked = _mask_literals(expression)
    if ";" in masked or "/*" in masked or "*/" in masked:
        raise ValueError("SAS filter expression cannot contain statement separators or comments.")
    if "%" in masked or "&" in masked:
        raise ValueError("SAS filter expression cannot contain macro references or macro calls.")
    if match := _FORBIDDEN_WORDS.search(masked):
        raise ValueError(f"SAS filter expression cannot contain the {match.group(0).lower()} statement keyword.")
    if _NARRATIVE_WORDS.search(masked):
        raise ValueError("SAS filter expression contains narrative review text instead of executable logic.")

    _validate_balanced_parentheses(masked)
    return expression


def _mask_literals(value: str) -> str:
    masked = list(value)
    index = 0
    while index < len(value):
        character = value[index]
        if character not in {'"', "'"}:
            index += 1
            continue
        quote = character
        masked[index] = " "
        index += 1
        while index < len(value):
            masked[index] = " "
            if value[index] == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                    masked[index] = " "
                else:
                    break
            index += 1
        else:
            raise ValueError("SAS filter expression contains an unterminated string literal.")
        index += 1
    return "".join(masked)


def _validate_balanced_parentheses(value: str) -> None:
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("SAS filter expression has unbalanced parentheses.")
    if depth:
        raise ValueError("SAS filter expression has unbalanced parentheses.")
