import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.parsers import parse_edc_source, parse_xlsx


def test_json_edc_extraction_preserves_file_context(tmp_path) -> None:
    source = tmp_path / "edc.json"
    source.write_text('{"study": "SYN-101", "forms": []}', encoding="utf-8")

    extracted = json.loads(parse_edc_source(source))

    assert extracted == {
        "file": "edc.json",
        "format": "json",
        "content": {"study": "SYN-101", "forms": []},
    }


def test_xlsx_edc_extraction_preserves_sheet_and_row_numbers(tmp_path) -> None:
    source = tmp_path / "edc.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Fields"
    sheet.append(["Dataset", "Variable", "Label"])
    sheet.append(["RAW_DM", "AGE", "Age"])
    workbook.save(source)

    extracted = json.loads(parse_edc_source(source))

    assert extracted["file"] == "edc.xlsx"
    assert extracted["sheets"][0]["name"] == "Fields"
    assert extracted["sheets"][0]["rows"][1] == {
        "row": 2,
        "values": ["RAW_DM", "AGE", "Age"],
    }


@pytest.mark.parametrize("parser", [parse_edc_source, parse_xlsx])
def test_xlsx_parsers_fail_closed_instead_of_returning_partial_rows(
    tmp_path,
    monkeypatch,
    parser,
) -> None:
    source = tmp_path / "too-many-rows.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Dataset", "Variable"])
    sheet.append(["DM", "USUBJID"])
    sheet.append(["DM", "AGE"])
    workbook.save(source)
    monkeypatch.setattr(
        "app.parsers.get_settings",
        lambda: SimpleNamespace(max_xlsx_rows_per_sheet=2),
    )

    with pytest.raises(HTTPException, match="no partial workbook was used"):
        parser(source)
