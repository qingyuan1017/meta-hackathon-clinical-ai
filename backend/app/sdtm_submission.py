from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lxml import etree

from .artifacts import sha256_file
from .schemas import SDTMPlan
from .schemas.sdtm_workbench import RawDatasetInventory
from .sdtm_execution import list_attempts
from .sdtm_workbench import read_state


PACKAGE_NAME = "sdtm-submission-package.zip"
PACKAGE_FOLDERS = ("data", "define", "raw", "spec", "program")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


@dataclass(frozen=True)
class PackageMember:
    archive_name: str
    payload: bytes


def refresh_submission_package(job_dir: Path, plan: SDTMPlan, output_dir: Path | None = None) -> Path:
    """Build the explicit, reviewable SDTM package without changing the audit bundle."""

    output_dir = output_dir or job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    package_path = output_dir / PACKAGE_NAME
    state = read_state(job_dir)
    members: list[PackageMember] = []
    omissions: list[dict[str, str]] = []

    _add_generated_data(job_dir, state.lifecycle.execution, members, omissions)
    _add_define_artifacts(output_dir, members, omissions)
    _add_raw_inputs(job_dir, state.inputs.raw_datasets, members, omissions)
    _add_specs(output_dir, members, omissions)
    _add_programs(output_dir, members, omissions)

    contents = [
        {
            "path": member.archive_name,
            "size_bytes": len(member.payload),
            "sha256": _sha256_bytes(member.payload),
        }
        for member in sorted(members, key=lambda item: item.archive_name.casefold())
    ]
    manifest = {
        "schema_version": "1.0",
        "package_type": "draft-sdtm-submission-artifacts",
        "study_name": plan.study_name,
        "standards": {"sdtm": plan.standard, "define_xml": plan.define_standard},
        "layout": {
            "data": "Current generated SDTM XPT datasets from the latest passed execution.",
            "define": "Define-XML, stylesheet, diagnostics, cSDRG, and aCRF when available.",
            "raw": "Original uploaded raw CSV/XPT datasets when available.",
            "spec": "Approved SDTM mapping and source specifications.",
            "program": "Current reviewed per-domain R and export-only SAS programs.",
        },
        "contents": contents,
        "omissions": omissions,
        "claims": {
            "draft_artifacts_only": True,
            "generation_implies_conformance": False,
            "generation_implies_submission_readiness": False,
            "sas_programs_were_executed": False,
        },
    }
    members.append(
        PackageMember(
            "package-manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
    )

    temporary = package_path.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for folder in PACKAGE_FOLDERS:
            _write_zip_entry(archive, f"{folder}/", b"", is_directory=True)
        for member in sorted(members, key=lambda item: item.archive_name.casefold()):
            _write_zip_entry(archive, member.archive_name, member.payload)
    temporary.replace(package_path)
    return package_path


def _add_generated_data(job_dir: Path, execution_status: str, members: list[PackageMember], omissions: list[dict[str, str]]) -> None:
    if execution_status != "passed":
        omissions.append({"folder": "data", "reason": "No current passed R execution is available; generated XPT data are omitted."})
        return
    attempts = [attempt for attempt in list_attempts(job_dir) if attempt.status == "passed"]
    if not attempts:
        omissions.append({"folder": "data", "reason": "Execution is marked passed but no passed execution record is available."})
        return
    attempt = attempts[-1]
    attempt_output = job_dir / "sdtm" / "executions" / attempt.attempt_id / "output"
    added = 0
    for output in sorted(attempt.outputs, key=lambda item: item.name.casefold()):
        filename = _portable_basename(output.name)
        if filename is None:
            continue
        source = attempt_output / filename
        if source.suffix.lower() != ".xpt" or not source.is_file():
            continue
        if sha256_file(source) != output.sha256:
            omissions.append({"folder": "data", "reason": f"{filename} was omitted because its hash no longer matches the passed execution record."})
            continue
        members.append(PackageMember(f"data/{filename.lower()}", source.read_bytes()))
        added += 1
    if not added:
        omissions.append({"folder": "data", "reason": "The latest passed execution has no intact XPT outputs to package."})


def _add_define_artifacts(output_dir: Path, members: list[PackageMember], omissions: list[dict[str, str]]) -> None:
    define_path = output_dir / "define.xml"
    if define_path.is_file():
        members.append(PackageMember("define/define.xml", _package_define_xml(define_path)))
    else:
        omissions.append({"folder": "define", "reason": "define.xml is unavailable."})

    aliases = {
        "define.xsl": "define/define.xsl",
        "define-diagnostics.json": "define/define-diagnostics.json",
        "csdrg.pdf": "define/csdrg.pdf",
        "csdrg.md": "define/csdrg.md",
        "csdrg.json": "define/csdrg.json",
        "annotated-crf.pdf": "define/acrf.pdf",
        "acrf-annotations.json": "define/acrf-annotations.json",
    }
    for source_name, archive_name in aliases.items():
        source = output_dir / source_name
        if source.is_file():
            members.append(PackageMember(archive_name, source.read_bytes()))
    if not (output_dir / "csdrg.pdf").is_file():
        omissions.append({"folder": "define", "reason": "cSDRG PDF is unavailable."})
    if not (output_dir / "annotated-crf.pdf").is_file():
        omissions.append({"folder": "define", "reason": "No aCRF is available because no searchable blank CRF was supplied or annotated."})


def _add_raw_inputs(
    job_dir: Path,
    inventories: list[RawDatasetInventory],
    members: list[PackageMember],
    omissions: list[dict[str, str]],
) -> None:
    added = 0
    for inventory in sorted(inventories, key=lambda item: item.original_name.casefold()):
        source = job_dir / "input" / inventory.stored_name
        original_name = _portable_basename(inventory.original_name)
        if original_name is None or not source.is_file():
            continue
        if sha256_file(source) != inventory.sha256:
            omissions.append({"folder": "raw", "reason": f"{original_name} was omitted because its hash no longer matches the input inventory."})
            continue
        members.append(PackageMember(f"raw/{original_name}", source.read_bytes()))
        added += 1
    if not added:
        omissions.append({"folder": "raw", "reason": "No intact raw CSV/XPT inputs were supplied."})


def _add_specs(output_dir: Path, members: list[PackageMember], omissions: list[dict[str, str]]) -> None:
    names = ("sdtm-mapping.xlsx", "sdtm-mapping.json", "edc-source-specification.json")
    for name in names:
        source = output_dir / name
        if source.is_file():
            members.append(PackageMember(f"spec/{name}", source.read_bytes()))
    if not any(member.archive_name.startswith("spec/") for member in members):
        omissions.append({"folder": "spec", "reason": "No mapping or source specification is available."})


def _add_programs(output_dir: Path, members: list[PackageMember], omissions: list[dict[str, str]]) -> None:
    programs = sorted(
        [*output_dir.glob("build-*.R"), *output_dir.glob("build-*.sas")],
        key=lambda path: path.name.casefold(),
    )
    for source in programs:
        members.append(PackageMember(f"program/{source.name}", source.read_bytes()))
    suffixes = {source.suffix.lower() for source in programs}
    if ".r" not in suffixes:
        omissions.append({"folder": "program", "reason": "No reviewed R programs are available."})
    if ".sas" not in suffixes:
        omissions.append({"folder": "program", "reason": "No export-only SAS programs are available."})


def _package_define_xml(path: Path) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    tree = etree.parse(str(path), parser)
    for leaf in tree.xpath("//*[local-name()='leaf']"):
        href = leaf.get(_XLINK_HREF)
        if not href:
            continue
        if href.lower().endswith(".xpt"):
            leaf.set(_XLINK_HREF, f"../data/{PurePosixPath(href).name.lower()}")
        elif href == "annotated-crf.pdf":
            leaf.set(_XLINK_HREF, "acrf.pdf")
    return etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
        doctype=tree.docinfo.doctype or None,
    )


def _write_zip_entry(archive: zipfile.ZipFile, name: str, payload: bytes, *, is_directory: bool = False) -> None:
    info = zipfile.ZipInfo(name, _ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o40755 if is_directory else 0o100644) << 16
    archive.writestr(info, payload)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _portable_basename(value: str) -> str | None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        return None
    return value
