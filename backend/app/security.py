from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, UploadFile


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
IDENTIFIER_PATTERNS: dict[str, re.Pattern[str]] = {
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "US Social Security number": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "medical-record identifier": re.compile(r"\b(?:MRN|medical record(?: number)?)\s*[:#-]?\s*[A-Z0-9]{5,}\b", re.I),
    "phone number": re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
}

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".json",
    ".xlsx",
    ".csv",
    ".xpt",
}


def sanitize_filename(name: str) -> str:
    candidate = SAFE_NAME.sub("_", Path(name).name).strip("._")
    return candidate[:180] or "upload"


def detect_identifiers(text: str) -> list[str]:
    return [label for label, pattern in IDENTIFIER_PATTERNS.items() if pattern.search(text)]


def validate_upload_metadata(upload: UploadFile) -> str:
    name = sanitize_filename(upload.filename or "upload")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or 'unknown'}")
    return name


def verify_signature(path: Path) -> None:
    suffix = path.suffix.lower()
    prefix = path.read_bytes()[:8]
    if suffix == ".pdf" and not prefix.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail=f"{path.name} is not a valid PDF file.")
    if suffix in {".docx", ".xlsx"} and not prefix.startswith(b"PK"):
        raise HTTPException(status_code=415, detail=f"{path.name} is not a valid Office document.")
    if suffix == ".xpt" and b"SAS" not in path.read_bytes()[:160]:
        raise HTTPException(status_code=415, detail=f"{path.name} is not a recognizable SAS transport file.")
