import json

from openpyxl import Workbook

from app.parsers import parse_edc_source


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
