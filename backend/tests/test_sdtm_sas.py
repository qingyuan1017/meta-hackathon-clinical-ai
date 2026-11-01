from __future__ import annotations

import pytest

from app.sdtm_sas import normalize_sas_filter_expression


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("not missing(AETERM)", "not missing(AETERM)"),
        ("not missing(SRC_VAL) or DASTAT = 'NOT DONE'", "not missing(SRC_VAL) or DASTAT = 'NOT DONE'"),
        ("upcase(strip(FLAG)) in ('Y', 'YES')", "upcase(strip(FLAG)) in ('Y', 'YES')"),
    ],
)
def test_normalize_sas_filter_expression_accepts_boolean_conditions(source: str, expected: str) -> None:
    assert normalize_sas_filter_expression(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "where not missing(AETERM)",
        "if not missing(AETERM)",
        "FLAG = 'Y'; run;",
        "CMQUST_CODED indicates 'No'; exact value to confirm during review",
        "IEORRES_src indicates not met",
        "not missing(AETERM",
        "FLAG = 'Y",
        "%sysfunc(fileexist(path))",
        "&reviewed_condition",
    ],
)
def test_normalize_sas_filter_expression_rejects_statements_prose_and_macros(source: str) -> None:
    with pytest.raises(ValueError):
        normalize_sas_filter_expression(source)
