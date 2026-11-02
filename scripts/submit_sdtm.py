"""Submit local SDTM inputs to the Clinical AI Workbench multipart API."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
ALLOWED_EXTENSIONS = {
    "metadata": {".json", ".xlsx"},
    "raw dataset": {".csv", ".xpt"},
    "blank CRF": {".pdf"},
    "validation report": {".csv", ".xlsx"},
}
CONTENT_TYPES = {
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".xpt": "application/octet-stream",
    ".pdf": "application/pdf",
}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Upload local EDC metadata and optional SDTM evidence to the Clinical AI Workbench. "
            "Files must contain only synthetic or de-identified data."
        )
    )
    parser.add_argument(
        "--metadata",
        nargs="+",
        required=True,
        metavar="PATH",
        help="One or more EDC JSON/XLSX files (required).",
    )
    parser.add_argument(
        "--raw",
        nargs="*",
        default=[],
        metavar="PATH",
        help="Optional synthetic raw CSV/XPT datasets.",
    )
    parser.add_argument("--crf", metavar="PATH", help="Optional searchable blank CRF PDF.")
    parser.add_argument(
        "--validation-report",
        metavar="PATH",
        help="Optional Pinnacle 21 CSV/XLSX report.",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        choices=("r", "sas"),
        default=("r", "sas"),
        help="Program languages to generate (default: r sas).",
    )
    parser.add_argument("--title", help="Optional job title.")
    parser.add_argument(
        "--api-url",
        default=os.getenv("WORKBENCH_API_URL", DEFAULT_API_URL),
        help=f"Workbench API base URL (default: WORKBENCH_API_URL or {DEFAULT_API_URL}).",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--acknowledge-deidentified",
        action="store_true",
        required=True,
        help="Required confirmation that every input is synthetic or de-identified and contains no PHI.",
    )
    return parser


def _resolve_paths(values: Sequence[str], *, label: str) -> list[Path]:
    allowed = ALLOWED_EXTENSIONS[label]
    resolved: list[Path] = []
    for value in values:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"{label.capitalize()} path is not a file: {path}")
        if path.suffix.lower() not in allowed:
            expected = ", ".join(sorted(allowed))
            raise ValueError(f"Unsupported {label} file {path.name}; expected: {expected}")
        resolved.append(path)
    return resolved


def _safe_filename(path: Path) -> str:
    candidate = SAFE_NAME.sub("_", path.name).strip("._")
    return candidate[:180] or "upload"


def _quote_header(value: str) -> str:
    return value.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")


def _multipart_body(
    *,
    options: dict[str, object],
    metadata: Sequence[Path],
    raw: Sequence[Path],
    crf: Path | None,
    validation_report: Path | None,
) -> tuple[bytes, str]:
    boundary = f"clinical-ai-{uuid4().hex}"
    output = BytesIO()

    def write(value: str | bytes) -> None:
        output.write(value.encode("utf-8") if isinstance(value, str) else value)

    def add_field(name: str, value: str) -> None:
        write(f"--{boundary}\r\n")
        write(f'Content-Disposition: form-data; name="{_quote_header(name)}"\r\n\r\n')
        write(value)
        write("\r\n")

    def add_file(name: str, path: Path) -> None:
        filename = _safe_filename(path)
        content_type = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        write(f"--{boundary}\r\n")
        write(
            f'Content-Disposition: form-data; name="{_quote_header(name)}"; '
            f'filename="{_quote_header(filename)}"\r\n'
        )
        write(f"Content-Type: {content_type}\r\n\r\n")
        write(path.read_bytes())
        write("\r\n")

    add_field("options", json.dumps(options, separators=(",", ":")))
    for path in metadata:
        add_file("files", path)
    for path in raw:
        add_file("raw_files", path)
    if crf is not None:
        add_file("crf_file", crf)
    if validation_report is not None:
        add_file("validation_report", validation_report)
    write(f"--{boundary}--\r\n")
    return output.getvalue(), boundary


def submit(args: argparse.Namespace) -> dict[str, object]:
    if not args.acknowledge_deidentified:
        raise ValueError("Explicit synthetic/de-identified-data acknowledgement is required.")
    metadata = _resolve_paths(args.metadata, label="metadata")
    raw = _resolve_paths(args.raw, label="raw dataset")
    crf = _resolve_paths([args.crf], label="blank CRF")[0] if args.crf else None
    validation_report = (
        _resolve_paths([args.validation_report], label="validation report")[0]
        if args.validation_report
        else None
    )
    options: dict[str, object] = {
        "deidentified_acknowledged": bool(args.acknowledge_deidentified),
        "languages": list(dict.fromkeys(args.languages)),
    }
    if args.title:
        options["title"] = args.title
    body, boundary = _multipart_body(
        options=options,
        metadata=metadata,
        raw=raw,
        crf=crf,
        validation_report=validation_report,
    )
    endpoint = f"{args.api_url.rstrip('/')}/jobs/sdtm"
    headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    api_token = os.getenv("WORKBENCH_API_TOKEN", "").strip()
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    request = Request(endpoint, data=body, method="POST", headers=headers)
    with urlopen(request, timeout=args.timeout) as response:  # noqa: S310 - URL is user-configurable by design.
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise RuntimeError("Workbench returned an unexpected non-object response.")
    return parsed


def _http_error_detail(error: HTTPError) -> str:
    payload = error.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return payload or error.reason
    if isinstance(parsed, dict) and "detail" in parsed:
        return str(parsed["detail"])
    return str(parsed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = submit(args)
    except HTTPError as error:
        print(f"SDTM submission failed (HTTP {error.code}): {_http_error_detail(error)}", file=sys.stderr)
        return 1
    except URLError as error:
        print(f"SDTM submission failed: {error.reason}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"SDTM submission failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
