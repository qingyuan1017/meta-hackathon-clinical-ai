from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

try:
    import resource
except ImportError:  # pragma: no cover - the deployed runner image is Linux
    resource = None  # type: ignore[assignment]


PROHIBITED = re.compile(
    r"(?i)(?:system2?\s*\(|shell\s*\(|download\.file\s*\(|install\.packages\s*\(|"
    r"socketConnection\s*\(|url\s*\(|curl::|httr2?::|processx::|parallel::|\.\.\/|/etc/|/proc/)"
)
MAX_PROGRAM_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 100 * 1024 * 1024


class OutputPayload(BaseModel):
    name: str
    content_base64: str


class ExecutionPayload(BaseModel):
    status: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    runtime: dict[str, str] = Field(default_factory=dict)
    outputs: list[OutputPayload] = Field(default_factory=list)


app = FastAPI(title="Clinical AI isolated SDTM R runner", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok" if shutil.which("Rscript") else "unavailable"}


@app.post("/execute", response_model=ExecutionPayload)
async def execute(
    program: UploadFile = File(...),
    raw_files: list[UploadFile] = File(default=[]),
    timeout_seconds: int = Form(180, ge=1, le=600),
) -> ExecutionPayload:
    program_bytes = await program.read(MAX_PROGRAM_BYTES + 1)
    if len(program_bytes) > MAX_PROGRAM_BYTES:
        raise HTTPException(status_code=413, detail="Program is too large.")
    try:
        source = program_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Program must be UTF-8 text.") from exc
    if PROHIBITED.search(source):
        raise HTTPException(status_code=422, detail="Program contains prohibited behavior.")
    if not raw_files:
        raise HTTPException(status_code=422, detail="At least one raw dataset is required.")

    with tempfile.TemporaryDirectory(prefix="sdtm-run-") as root_name:
        root = Path(root_name)
        input_dir = root / "input"
        output_dir = root / "output"
        input_dir.mkdir(mode=0o700)
        output_dir.mkdir(mode=0o700)
        program_path = root / "program.R"
        program_path.write_text(source, encoding="utf-8")
        total = 0
        for upload in raw_files:
            name = Path(upload.filename or "").name
            if name != upload.filename or Path(name).suffix.lower() not in {".csv", ".xpt"}:
                raise HTTPException(status_code=422, detail="Raw inputs must be simple CSV/XPT filenames.")
            content = await upload.read(MAX_INPUT_BYTES + 1)
            total += len(content)
            if total > MAX_INPUT_BYTES:
                raise HTTPException(status_code=413, detail="Raw inputs exceed the runner limit.")
            (input_dir / name).write_bytes(content)
        for path in input_dir.iterdir():
            path.chmod(0o444)
        input_dir.chmod(0o555)
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "R_LIBS_SITE": os.environ.get("R_LIBS_SITE", ""),
            "SDTM_INPUT_DIR": str(input_dir),
            "SDTM_OUTPUT_DIR": str(output_dir),
            "HOME": str(root / "empty-home"),
            "TMPDIR": str(root / "tmp"),
        }
        Path(environment["HOME"]).mkdir()
        Path(environment["TMPDIR"]).mkdir()
        try:
            completed = subprocess.run(
                ["Rscript", "--vanilla", str(program_path)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                preexec_fn=_limits,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionPayload(status="timed_out", exit_code=None, stdout=_bounded(exc.stdout), stderr=_bounded(exc.stderr), runtime=_runtime())
        outputs = [
            OutputPayload(name=path.name, content_base64=base64.b64encode(path.read_bytes()).decode("ascii"))
            for path in sorted(output_dir.glob("*.xpt"))
            if path.stat().st_size <= 100 * 1024 * 1024
        ]
        return ExecutionPayload(
            status="passed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            stdout=_bounded(completed.stdout),
            stderr=_bounded(completed.stderr),
            runtime=_runtime(),
            outputs=outputs,
        )


def _limits() -> None:
    if resource is None:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024**2, 200 * 1024**2))


def _bounded(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return (value or "")[-20_000:].replace("\x00", "")


def _runtime() -> dict[str, str]:
    try:
        version = subprocess.run(["Rscript", "--version"], capture_output=True, text=True, timeout=5, check=False)
        r_version = (version.stderr or version.stdout).strip()
    except (OSError, subprocess.SubprocessError):
        r_version = "unavailable"
    return {"runner": "clinical-ai-sdtm-runner/0.1.0", "r": r_version, "packages": "dplyr,readr,haven (image-pinned)"}

