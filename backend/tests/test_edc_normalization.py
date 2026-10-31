from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.edc_normalization import normalize_edc_json
from app.use_cases.base import UseCaseContext
from app.use_cases.sdtm import SDTMUseCase


def test_normalizes_every_domain_and_variable_with_json_path_provenance(tmp_path) -> None:
    source = tmp_path / "source.json"
    domains = [
        {
            "name": f"D{index:02d}",
            "variables": [
                {
                    "dataset": f"D{index:02d}",
                    "name": f"VAR{variable}",
                    "data_type": "character" if variable == 0 else "numeric",
                    "length": 12,
                    "description": f"Variable {variable}",
                }
                for variable in range(3)
            ],
        }
        for index in range(68)
    ]
    source.write_text(
        json.dumps({"name": "COMPLETE-STUDY", "domains": domains, "cts": []}),
        encoding="utf-8",
    )

    normalized = normalize_edc_json(source)

    assert normalized is not None
    assert normalized.adapter == "root-domains"
    assert normalized.specification.study_name == "COMPLETE-STUDY"
    assert len(normalized.specification.datasets) == 68
    assert sum(len(dataset.variables) for dataset in normalized.specification.datasets) == 204
    assert normalized.specification.datasets[-1].provenance.json_path == "$.domains[67]"
    assert (
        normalized.specification.datasets[-1].variables[-1].provenance.json_path
        == "$.domains[67].variables[2]"
    )
    assert normalized.specification.datasets[0].variables[0].data_type == "text"
    assert normalized.specification.datasets[0].variables[1].data_type == "decimal"


def test_generic_discovery_handles_unfamiliar_collection_names(tmp_path) -> None:
    source = tmp_path / "unfamiliar.json"
    source.write_text(
        json.dumps(
            {
                "study": {"id": "SYN-GENERIC"},
                "exports": [
                    {
                        "schemaName": "RAW_DM",
                        "attributes": [
                            {
                                "columnName": "SUBJID",
                                "dataType": "string",
                                "title": "Subject identifier",
                                "mandatory": "yes",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    normalized = normalize_edc_json(source)

    assert normalized is not None
    assert normalized.adapter == "generic-recursive"
    assert normalized.specification.study_name == "SYN-GENERIC"
    dataset = normalized.specification.datasets[0]
    assert dataset.name == "RAW_DM"
    assert dataset.provenance.json_path == "$.exports[0]"
    assert dataset.variables[0].name == "SUBJID"
    assert dataset.variables[0].required is True
    assert dataset.variables[0].provenance.json_path == "$.exports[0].attributes[0]"


def test_dictionary_collections_and_codelists_are_preserved(tmp_path) -> None:
    source = tmp_path / "dictionary.json"
    source.write_text(
        json.dumps(
            {
                "study_name": "SYN-DICT",
                "datasets": {
                    "RAW_AE": {
                        "fields": {
                            "AESEV": {
                                "label": "Severity",
                                "type": "choice",
                                "codelist": "SEVERITY",
                            }
                        }
                    }
                },
                "codelists": {"SEVERITY": {"values": ["MILD", "MODERATE", "SEVERE"]}},
            }
        ),
        encoding="utf-8",
    )

    normalized = normalize_edc_json(source)

    assert normalized is not None
    assert normalized.specification.datasets[0].name == "RAW_AE"
    assert normalized.specification.datasets[0].variables[0].name == "AESEV"
    assert normalized.specification.datasets[0].variables[0].codelist == "SEVERITY"
    assert normalized.specification.codelists[0].values == ["MILD", "MODERATE", "SEVERE"]


async def test_sdtm_review_uses_complete_deterministic_json_without_model_call(tmp_path) -> None:
    source = tmp_path / "large-edc.json"
    source.write_text(
        json.dumps(
            {
                "name": "SYN-LARGE",
                "domains": [
                    {
                        "name": f"D{index:02d}",
                        "variables": [
                            {"name": "ID", "description": "Identifier", "data_type": "character"}
                        ],
                    }
                    for index in range(24)
                ],
            }
        ),
        encoding="utf-8",
    )
    progress = tmp_path / "agent" / "progress.json"
    settings = Settings(
        _env_file=None,
        meta_api_key="test",
        meta_model="test",
        max_source_chunks=1,
        chunk_characters=100,
        cdisc_mcp_enabled=False,
        clinicalgov_mcp_enabled=False,
        openfda_mcp_enabled=False,
        bioportal_mcp_enabled=False,
        pubmed_mcp_enabled=False,
    )
    rejecting_ai = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_: pytest.fail("The model must not be called for recognized JSON metadata.")
                )
            )
        )
    )

    prepared = await SDTMUseCase().prepare_review(
        UseCaseContext(
            inputs=[source],
            options={},
            ai=rejecting_ai,
            settings=settings,
            agent_progress_path=progress,
        )
    )

    assert prepared is not None
    assert prepared.review_stage == "edc_source"
    assert len(prepared.value.datasets) == 24
    trace = json.loads(progress.read_text(encoding="utf-8"))
    assert trace["model"] == "deterministic-json-normalizer"
    assert trace["events"][-1]["output_details"] == {
        "Datasets": 24,
        "Variables": 24,
        "Human approval required": True,
    }


async def test_large_unrecognized_json_fails_instead_of_silent_truncation(tmp_path) -> None:
    source = tmp_path / "unknown.json"
    source.write_text(
        json.dumps({"payload": [{"opaque": "x" * 500} for _ in range(8)]}),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        meta_api_key="test",
        meta_model="test",
        max_source_chunks=1,
        chunk_characters=100,
        cdisc_mcp_enabled=False,
        clinicalgov_mcp_enabled=False,
        openfda_mcp_enabled=False,
        bioportal_mcp_enabled=False,
        pubmed_mcp_enabled=False,
    )

    with pytest.raises(ValueError, match="unrecognized metadata structure.*complete-read limit"):
        await SDTMUseCase().prepare_review(
            UseCaseContext(
                inputs=[source],
                options={},
                ai=SimpleNamespace(),
                settings=settings,
            )
        )
