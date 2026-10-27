from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz
from docx import Document
from fastapi import HTTPException
from openpyxl import load_workbook

from .config import get_settings


def parse_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        document = Document(path)
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        tables = []
        for table in document.tables:
            for row in table.rows:
                values = [cell.text.strip() for cell in row.cells]
                if any(values):
                    tables.append(" | ".join(values))
        return "\n".join([*paragraphs, *tables])
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid JSON in {path.name}: {exc.msg}") from exc
        return json.dumps(value, indent=2, ensure_ascii=False)
    if suffix == ".xlsx":
        return parse_xlsx(path)
    raise HTTPException(status_code=415, detail=f"No parser for {suffix}")


def parse_pdf(path: Path) -> str:
    settings = get_settings()
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to read PDF {path.name}.") from exc
    if document.page_count > settings.max_pdf_pages:
        document.close()
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds the {settings.max_pdf_pages}-page limit.",
        )
    pages = [page.get_text("text") for page in document]
    document.close()
    return "\n\n".join(pages)


def parse_xlsx(path: Path) -> str:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to read workbook {path.name}.") from exc
    result: dict[str, list[list[object]]] = {}
    for sheet in workbook.worksheets:
        rows: list[list[object]] = []
        for row in sheet.iter_rows(values_only=True):
            values = [value for value in row]
            if any(value is not None for value in values):
                rows.append(values)
            if len(rows) >= 2_000:
                break
        result[sheet.title] = rows
    workbook.close()
    return json.dumps(result, indent=2, default=str)


def chunk_text(text: str, chunk_size: int | None = None) -> list[str]:
    size = chunk_size or get_settings().chunk_characters
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > size:
            chunks.append(current)
            current = ""
        if len(paragraph) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(paragraph[index : index + size] for index in range(0, len(paragraph), size))
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks or [""]
