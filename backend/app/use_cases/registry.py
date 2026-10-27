from __future__ import annotations

from .base import ClinicalUseCase
from .clinical_document import ClinicalDocumentUseCase, DOCUMENT_TYPES
from .edc_design import EDCDesignUseCase
from .protocol_extraction import ProtocolExtractionUseCase
from .sdtm import SDTMUseCase
from .tlf import TLFUseCase


_REGISTERED: tuple[ClinicalUseCase, ...] = (
    ProtocolExtractionUseCase(),
    ClinicalDocumentUseCase(),
    EDCDesignUseCase(),
    SDTMUseCase(),
    TLFUseCase(),
)

USE_CASES: dict[str, ClinicalUseCase] = {item.descriptor.id: item for item in _REGISTERED}


def get_use_case(use_case_id: str) -> ClinicalUseCase:
    try:
        return USE_CASES[use_case_id]
    except KeyError as exc:
        raise ValueError(f"Unknown use case: {use_case_id}") from exc
