from __future__ import annotations

import re


_SAFE_BASE_CALLS = frozenset(
    {
        "abs",
        "as.character",
        "as.Date",
        "as.double",
        "as.integer",
        "as.logical",
        "as.numeric",
        "as.POSIXct",
        "as.POSIXlt",
        "as.vector",
        "ave",
        "c",
        "ceiling",
        "difftime",
        "factor",
        "floor",
        "format",
        "gsub",
        "ifelse",
        "is.character",
        "is.na",
        "is.numeric",
        "length",
        "match",
        "max",
        "min",
        "nchar",
        "paste",
        "paste0",
        "pmax",
        "pmin",
        "round",
        "rep",
        "seq_along",
        "seq_len",
        "sprintf",
        "strptime",
        "sub",
        "substr",
        "substring",
        "suppressWarnings",
        "tolower",
        "toupper",
        "trimws",
        "trunc",
    }
)

_SAFE_DPLYR_CALLS = frozenset(
    {
        "between",
        "case_match",
        "case_when",
        "coalesce",
        "dense_rank",
        "first",
        "if_else",
        "lag",
        "last",
        "lead",
        "min_rank",
        "n",
        "na_if",
        "nth",
        "recode",
        "recode_factor",
        "row_number",
    }
)

_CALL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.$])([A-Za-z.][A-Za-z0-9._]*(?:::[A-Za-z.][A-Za-z0-9._]*)?)\s*\("
)
_MEMBER_CALL_PATTERN = re.compile(r"\$\s*[A-Za-z.][A-Za-z0-9._]*\s*\(")
_BACKTICK_IDENTIFIER = re.compile(r"[A-Za-z_.][A-Za-z0-9._]*")


def normalize_r_mapping_expression(value: str) -> str:
    """Return one safe R right-hand-side expression with review-only comments removed."""

    expression = _strip_review_comments(value.strip())
    if not expression:
        raise ValueError("R mapping expression is empty after removing review comments.")
    if re.match(r"(?i)^TODO\s*:", expression):
        return "NA"
    if "\n" in expression or "\r" in expression:
        raise ValueError("R mapping expression must be a single line.")

    masked = _mask_literals(expression)
    if ";" in masked or "{" in masked or "}" in masked:
        raise ValueError("R mapping expression cannot contain statement separators or blocks.")
    if re.search(r"(?:<<-|<-|->>|->)", masked):
        raise ValueError("R mapping expression cannot assign values.")
    if ":::" in masked:
        raise ValueError("R mapping expression cannot access non-exported namespace members.")
    if _MEMBER_CALL_PATTERN.search(masked):
        raise ValueError("R mapping expression cannot invoke a function through a dynamic object member.")

    _validate_balanced_delimiters(masked)
    for match in _CALL_PATTERN.finditer(masked):
        call = match.group(1)
        if "::" in call:
            namespace, function = call.split("::", 1)
            if namespace != "dplyr" or function not in _SAFE_DPLYR_CALLS:
                raise ValueError(f"R mapping expression uses unapproved call {call}().")
        elif call not in _SAFE_BASE_CALLS and not call.startswith("TODO_"):
            raise ValueError(f"R mapping expression uses unapproved call {call}().")
    return expression.strip()


def _strip_review_comments(value: str) -> str:
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(value):
        character = value[index]
        if quote is not None:
            output.append(character)
            if character == "\\" and index + 1 < len(value):
                index += 1
                output.append(value[index])
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'"}:
            quote = character
            output.append(character)
            index += 1
            continue
        if character == "#":
            break
        if value.startswith("/*", index):
            closing = value.find("*/", index + 2)
            if closing < 0:
                raise ValueError("R mapping expression contains an unterminated review comment.")
            output.append(" ")
            index = closing + 2
            continue
        output.append(character)
        index += 1
    if quote is not None:
        raise ValueError("R mapping expression contains an unterminated string literal.")
    return "".join(output).rstrip()


def _mask_literals(value: str) -> str:
    masked = list(value)
    index = 0
    while index < len(value):
        character = value[index]
        if character in {'"', "'"}:
            quote = character
            masked[index] = " "
            index += 1
            while index < len(value):
                masked[index] = " "
                if value[index] == "\\" and index + 1 < len(value):
                    index += 1
                    masked[index] = " "
                elif value[index] == quote:
                    break
                index += 1
            else:
                raise ValueError("R mapping expression contains an unterminated string literal.")
        elif character == "`":
            closing = value.find("`", index + 1)
            if closing < 0:
                raise ValueError("R mapping expression contains an unterminated quoted identifier.")
            identifier = value[index + 1 : closing]
            if not _BACKTICK_IDENTIFIER.fullmatch(identifier):
                raise ValueError("R mapping expression contains an invalid quoted identifier.")
            index = closing
        index += 1
    return "".join(masked)


def _validate_balanced_delimiters(value: str) -> None:
    stack: list[str] = []
    pairs = {")": "(", "]": "["}
    for character in value:
        if character in "([":
            stack.append(character)
        elif character in pairs:
            if not stack or stack.pop() != pairs[character]:
                raise ValueError("R mapping expression has unbalanced delimiters.")
    if stack:
        raise ValueError("R mapping expression has unbalanced delimiters.")
