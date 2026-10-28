from __future__ import annotations

import json
from typing import Any

from usdm_info import __model_version__
from usdm_model import (
    Code,
    EligibilityCriterionItem,
    Organization,
    Study,
    StudyIdentifier,
    StudyRole,
    StudyTitle,
    StudyVersion,
    Wrapper,
)
from usdm_model.extension import ExtensionAttribute

from .schemas import StudySummary


USDM_VERSION = "4.0.0"
USDM_SYSTEM_NAME = "Clinical AI Artifact Workbench"
USDM_SYSTEM_VERSION = "0.1.0"
EXTENSION_BASE_URL = "https://clinical-ai-workbench.local/usdm/extension"
CT_CODE_SYSTEM = "http://www.cdisc.org"
CT_VERSION = "2025-09-26"


if __model_version__ != USDM_VERSION:
    raise RuntimeError(
        f"The installed CDISC USDM model is {__model_version__}; {USDM_VERSION} is required."
    )


def build_usdm(summary: StudySummary) -> Wrapper:
    """Map a reviewed extraction into a structurally valid CDISC USDM 4.0 wrapper."""

    study_name = _supported_scalar(summary.protocol_number) or _supported_scalar(summary.study_title)
    study_name = study_name or "extracted-study"
    titles = []
    if title := _supported_scalar(summary.study_title):
        titles.append(
            StudyTitle(
                id="STUDY-TITLE-1",
                text=title,
                type=_code(
                    identifier="CODE-STUDY-TITLE-OFFICIAL",
                    code="C207616",
                    decode="Official Study Title",
                ),
            )
        )

    eligibility_items = [
        *_eligibility_items(summary.inclusion_criteria, category="inclusion", prefix="INC"),
        *_eligibility_items(summary.exclusion_criteria, category="exclusion", prefix="EXC"),
    ]
    study_identifiers, roles, organizations = _sponsor_identity(summary)
    extensions = _summary_extensions(summary)
    version = StudyVersion(
        id="STUDY-VERSION-1",
        versionIdentifier="1.0-extracted-draft",
        rationale="Generated from the supplied protocol by the Clinical AI Artifact Workbench.",
        studyIdentifiers=study_identifiers,
        titles=titles,
        eligibilityCriterionItems=eligibility_items,
        roles=roles,
        organizations=organizations,
        extensionAttributes=extensions,
    )
    study = Study(
        name=study_name,
        label=_supported_scalar(summary.study_title),
        description=_supported_scalar(summary.study_design),
        versions=[version],
    )
    wrapper = Wrapper(
        study=study,
        usdmVersion=USDM_VERSION,
        systemName=USDM_SYSTEM_NAME,
        systemVersion=USDM_SYSTEM_VERSION,
    )
    return validate_usdm(wrapper.model_dump(mode="json"))


def validate_usdm(payload: dict[str, Any]) -> Wrapper:
    """Validate a payload with the official CDISC USDM 4.0 Pydantic model."""

    wrapper = Wrapper.model_validate(payload)
    if wrapper.usdmVersion != USDM_VERSION:
        raise ValueError(f"usdmVersion must be {USDM_VERSION}")
    return wrapper


def _summary_extensions(summary: StudySummary) -> list[ExtensionAttribute]:
    values: list[tuple[str, Any]] = [
        ("protocolNumber", summary.protocol_number),
        ("phase", summary.phase),
        ("indication", summary.indication),
        ("sponsor", summary.sponsor),
        ("studyDesign", summary.study_design),
        ("population", summary.population),
        ("sampleSize", summary.sample_size),
        ("duration", summary.duration),
        ("arms", summary.arms),
        ("objectives", [item.model_dump(mode="json") for item in summary.objectives]),
        ("visits", summary.visits),
        ("assessments", summary.assessments),
        ("safetyMonitoring", summary.safety_monitoring),
        ("ambiguities", summary.ambiguities),
    ]
    extensions: list[ExtensionAttribute] = []
    for index, (name, value) in enumerate(values, 1):
        if not _supported_value(value):
            continue
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        extensions.append(
            ExtensionAttribute(
                id=f"EXT-{index:02d}",
                url=f"{EXTENSION_BASE_URL}/{name}",
                valueString=rendered,
                instanceType="ExtensionAttribute",
            )
        )
    return extensions


def _sponsor_identity(
    summary: StudySummary,
) -> tuple[list[StudyIdentifier], list[StudyRole], list[Organization]]:
    sponsor = _supported_scalar(summary.sponsor)
    protocol_number = _supported_scalar(summary.protocol_number)
    if not sponsor or not protocol_number:
        return [], [], []

    organization_id = "ORGANIZATION-SPONSOR-1"
    organization = Organization(
        id=organization_id,
        name=sponsor,
        label=sponsor,
        type=_code(
            identifier="CODE-ORGANIZATION-SPONSOR",
            code="C70793",
            decode="Clinical Study Sponsor",
        ),
        identifierScheme="Sponsor-provided organization name",
        identifier=sponsor,
    )
    role = StudyRole(
        id="STUDY-ROLE-SPONSOR-1",
        name="Sponsor",
        label="Sponsor",
        description="Sponsor identified in the supplied protocol.",
        code=_code(
            identifier="CODE-STUDY-ROLE-SPONSOR",
            code="C70793",
            decode="Clinical Study Sponsor",
        ),
        organizationIds=[organization_id],
        appliesToIds=["STUDY-VERSION-1"],
    )
    identifier = StudyIdentifier(
        id="STUDY-IDENTIFIER-SPONSOR-1",
        text=protocol_number,
        scopeId=organization_id,
    )
    return [identifier], [role], [organization]


def _eligibility_items(
    criteria: list[str], *, category: str, prefix: str
) -> list[EligibilityCriterionItem]:
    items: list[EligibilityCriterionItem] = []
    for index, text in enumerate(criteria, 1):
        if not text.strip():
            continue
        items.append(
            EligibilityCriterionItem(
                id=f"ELIGIBILITY-{prefix}-{index:03d}",
                name=f"{prefix}-{index:03d}",
                text=text.strip(),
                extensionAttributes=[
                    ExtensionAttribute(
                        id=f"ELIGIBILITY-{prefix}-{index:03d}-CATEGORY",
                        url=f"{EXTENSION_BASE_URL}/eligibilityCategory",
                        valueString=category,
                        instanceType="ExtensionAttribute",
                    )
                ],
            )
        )
    return items


def _code(*, identifier: str, code: str, decode: str) -> Code:
    return Code(
        id=identifier,
        code=code,
        codeSystem=CT_CODE_SYSTEM,
        codeSystemVersion=CT_VERSION,
        decode=decode,
    )


def _supported_scalar(value: str) -> str | None:
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in {"not specified", "untitled study"}:
        return None
    return cleaned


def _supported_value(value: Any) -> bool:
    if isinstance(value, str):
        return _supported_scalar(value) is not None
    return bool(value)
