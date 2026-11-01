import asyncio
import json
from types import SimpleNamespace

import pytest
from app.agents import AGENTS, AgentOutcome, ClinicalAgentRunner, get_agent
from app.agents.protocol_extraction import PERSPECTIVE_AGENTS
from app.agents.sdtm import SOURCE_NORMALIZATION_AGENT, STAGE_AGENTS
from reportlab.pdfgen import canvas

from app.agents.runtime import verify_result
from app.ai import AIResponseError, MetaAIClient
from app.config import Settings
from app.schemas import (
    EDCDesign,
    EDCForm,
    EDCSourceSpecification,
    EDCVisit,
    SDTMDomainMappingPlan,
    SDTMPlan,
    SDTMRuleAugmentationPlan,
    SDTMVariableMappingPlan,
    StudySummary,
    TLFInventoryPlan,
)
from app.parsers import chunk_text
from app.use_cases.base import UseCaseContext
from app.use_cases.protocol_extraction import ProtocolExtractionUseCase
from app.use_cases.sdtm import SDTMUseCase
from app.use_cases.tlf import TLFUseCase
from tests.sdtm_helpers import read_plan, source


def test_sdtm_submission_requires_edc_but_not_crf() -> None:
    SDTMUseCase().validate_submission(["edc.xlsx"], {})
    SDTMUseCase().validate_submission(["edc.json", "blank-crf.pdf"], {})
    with pytest.raises(ValueError, match="EDC JSON or XLSX"):
        SDTMUseCase().validate_submission(["blank-crf.pdf"], {})


def test_sdtm_domain_mapping_accepts_reviewed_not_mapped_sources() -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-DISPOSITION",
            "datasets": [
                {
                    "name": name,
                    "label": label,
                    "variables": [
                        {"name": "ID", "label": "Identifier", "provenance": {"file": "edc.json"}}
                    ],
                    "provenance": {"file": "edc.json"},
                }
                for name, label in (("RAW_DM", "Demographics"), ("AUDIT_LOG", "Operational audit log"))
            ],
        }
    )
    mapped_only = {
        "study_name": "SYN-DISPOSITION",
        "domain_mappings": [
            {"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "Collected demographics"}
        ],
    }

    with pytest.raises(ValueError, match="missing dispositions: AUDIT_LOG"):
        SDTMUseCase.validate_domain_mapping(
            source_spec,
            SDTMDomainMappingPlan.model_validate(mapped_only),
        )

    reviewed = SDTMDomainMappingPlan.model_validate(
        {
            **mapped_only,
            "unmapped_datasets": [
                {
                    "source_dataset": "AUDIT_LOG",
                    "rationale": "Operational metadata is not submitted as an SDTM tabulation domain.",
                }
            ],
        }
    )
    SDTMUseCase.validate_domain_mapping(source_spec, reviewed)

    conflicting_payload = reviewed.model_dump()
    conflicting_payload["unmapped_datasets"] = [
        {
            "source_dataset": "RAW_DM",
            "rationale": "Incorrect conflicting disposition",
        }
    ]
    conflicting = SDTMDomainMappingPlan.model_validate(conflicting_payload)
    with pytest.raises(ValueError, match="both mapped and marked not mapped"):
        SDTMUseCase.validate_domain_mapping(source_spec, conflicting)


def test_sdtm_domain_mapping_distinguishes_stack_join_and_rejects_merge() -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-LB",
            "datasets": [
                {
                    "name": name,
                    "label": label,
                    "variables": [{"name": "USUBJID", "label": "Subject", "provenance": {"file": "edc.json"}}],
                    "provenance": {"file": "edc.json"},
                }
                for name, label in (("LB_HEMA", "Hematology"), ("LB_CHEM", "Chemistry"))
            ],
        }
    )
    stacked = SDTMDomainMappingPlan.model_validate(
        {
            "study_name": "SYN-LB",
            "domain_mappings": [
                {"source_dataset": "LB_HEMA", "target_domain": "LB", "relationship": "stack", "rationale": "Append hematology rows"},
                {"source_dataset": "LB_CHEM", "target_domain": "LB", "relationship": "stack", "rationale": "Append chemistry rows"},
            ],
        }
    )
    SDTMUseCase.validate_domain_mapping(source_spec, stacked)

    incomplete_stack = stacked.model_dump(mode="json")
    incomplete_stack["domain_mappings"][0]["relationship"] = "direct"
    with pytest.raises(ValueError, match="only one stack source"):
        SDTMUseCase.validate_domain_mapping(
            source_spec,
            SDTMDomainMappingPlan.model_validate(incomplete_stack),
        )

    legacy_merge = stacked.model_dump(mode="json")
    legacy_merge["domain_mappings"][0]["relationship"] = "merge"
    with pytest.raises(ValueError, match="relationship"):
        SDTMDomainMappingPlan.model_validate(legacy_merge)


def test_sdtm_variable_mapping_accepts_assigned_values_without_raw_sources() -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-ASSIGNED",
            "datasets": [
                {
                    "name": "RAW_DM",
                    "label": "Demographics",
                    "variables": [
                        {"name": "SUBJID", "label": "Subject", "provenance": {"file": "edc.json"}}
                    ],
                    "provenance": {"file": "edc.json"},
                }
            ],
        }
    )
    domain_mapping = SDTMDomainMappingPlan.model_validate(
        {
            "study_name": "SYN-ASSIGNED",
            "domain_mappings": [
                {"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "Demographics"}
            ],
        }
    )
    payload = {
        "study_name": "SYN-ASSIGNED",
        "datasets": [
            {
                "domain": "DM",
                "description": "Demographics",
                "record_plan": read_plan("DM", "RAW_DM").model_dump(mode="json"),
                "variables": [
                    {
                        "name": "STUDYID",
                        "label": "Study Identifier",
                        "mapping_type": "assigned",
                        "sources": [],
                        "origin": "Assigned",
                        "mapping_expression": "Assign the approved study identifier SYN-ASSIGNED.",
                    },
                    {
                        "name": "SUBJID",
                        "label": "Subject Identifier",
                        "sources": [source("RAW_DM", "SUBJID").model_dump(mode="json")],
                        "origin": "CRF",
                        "mapping_expression": "Direct",
                    },
                ],
            }
        ],
    }
    mapping = SDTMVariableMappingPlan.model_validate(payload)
    SDTMUseCase.validate_variable_mapping(source_spec, domain_mapping, mapping)

    invalid_payload = mapping.model_dump()
    invalid_payload["datasets"][0]["variables"][0]["mapping_type"] = "direct"
    invalid_payload["datasets"][0]["variables"][0]["sources"] = [
        {"dataset": "Assigned", "variable": "STUDYID", "role": "value"}
    ]
    invalid = SDTMVariableMappingPlan.model_validate(invalid_payload)
    with pytest.raises(ValueError, match="unknown source dataset Assigned"):
        SDTMUseCase.validate_variable_mapping(source_spec, domain_mapping, invalid)


def test_sdtm_variable_mapping_keeps_lineage_while_rule_stage_validates_record_plan() -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-MULTI",
            "datasets": [
                {
                    "name": "RAW_AE",
                    "label": "Adverse events",
                    "variables": [
                        {"name": "SUBJID", "label": "Subject", "provenance": {"file": "edc.json"}},
                        {"name": "AETERM", "label": "Term", "provenance": {"file": "edc.json"}},
                    ],
                    "provenance": {"file": "edc.json"},
                },
                {
                    "name": "RAW_SAE",
                    "label": "Serious adverse events",
                    "variables": [
                        {"name": "SUBJECT", "label": "Subject", "provenance": {"file": "edc.json"}},
                        {"name": "TERM", "label": "Term", "provenance": {"file": "edc.json"}},
                    ],
                    "provenance": {"file": "edc.json"},
                },
            ],
        }
    )
    domain_mapping = SDTMDomainMappingPlan.model_validate(
        {
            "study_name": "SYN-MULTI",
            "domain_mappings": [
                {"source_dataset": "RAW_AE", "target_domain": "AE", "relationship": "stack", "rationale": "AE stream"},
                {"source_dataset": "RAW_SAE", "target_domain": "AE", "relationship": "stack", "rationale": "SAE stream"},
            ],
        }
    )
    payload = {
        "study_name": "SYN-MULTI",
        "datasets": [
            {
                "domain": "AE",
                "description": "Adverse events",
                "variables": [
                    {
                        "name": "AETERM",
                        "label": "Reported Term",
                        "mapping_type": "coalesce",
                        "sources": [
                            {"dataset": "RAW_AE", "variable": "AETERM", "role": "value"},
                            {"dataset": "RAW_SAE", "variable": "TERM", "role": "value"},
                        ],
                        "mapping_expression": "Use the aligned term from each stacked source.",
                    }
                ],
            }
        ],
    }
    mapping = SDTMVariableMappingPlan.model_validate(payload)
    SDTMUseCase.validate_variable_mapping(source_spec, domain_mapping, mapping)
    assert "record_plan" not in mapping.datasets[0].model_dump(mode="json")

    record_plan = {
        "steps": [
            {"step_id": "read_ae", "operation": "read", "description": "Read AE", "output": "ae", "source_dataset": "RAW_AE"},
            {"step_id": "read_sae", "operation": "read", "description": "Read SAE", "output": "sae", "source_dataset": "RAW_SAE"},
            {"step_id": "stack", "operation": "stack", "description": "Stack event streams", "output": "events", "inputs": ["read_ae", "read_sae"]},
        ],
        "output_step": "stack",
    }
    rule_plan = SDTMRuleAugmentationPlan.model_validate({
        "study_name": "SYN-MULTI",
        "record_plans": [{"target_domain": "AE", "record_plan": record_plan}],
        "rule_augmentations": [{
            "rule_id": "AE-AETERM", "target_domain": "AE", "target_variable": "AETERM",
            "description": "Map term", "logic": "Coalesce stacked terms",
            "r_expression": '.data[["AETERM"]]', "sas_expression": "AETERM",
        }],
    })
    SDTMUseCase._validate_rule_batch("AE", mapping.datasets[0], domain_mapping.domain_mappings, rule_plan)

    joined_domain_payload = domain_mapping.model_dump(mode="json")
    joined_domain_payload["domain_mappings"][0]["relationship"] = "direct"
    joined_domain_payload["domain_mappings"][1]["relationship"] = "join"
    joined_domain_mapping = SDTMDomainMappingPlan.model_validate(joined_domain_payload)
    with pytest.raises(ValueError, match="require record-plan operation.*join"):
        SDTMUseCase._validate_rule_batch(
            "AE", mapping.datasets[0], joined_domain_mapping.domain_mappings, rule_plan
        )

    invalid_payload = rule_plan.model_dump(mode="json")
    invalid_payload["record_plans"][0]["record_plan"]["steps"][0]["inputs"] = ["stack"]
    invalid = SDTMRuleAugmentationPlan.model_validate(invalid_payload)
    with pytest.raises(ValueError, match="unavailable or later step stack"):
        SDTMUseCase._validate_rule_batch("AE", mapping.datasets[0], domain_mapping.domain_mappings, invalid)


def test_sdtm_rule_stage_requires_executable_filter_conditions() -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-FILTER",
            "datasets": [
                {
                    "name": "RAW_AE",
                    "label": "Adverse events",
                    "variables": [
                        {
                            "name": "AETERM",
                            "label": "Reported term",
                            "provenance": {"file": "edc.json"},
                        }
                    ],
                    "provenance": {"file": "edc.json"},
                }
            ],
        }
    )
    domain_mapping = SDTMDomainMappingPlan.model_validate(
        {
            "study_name": "SYN-FILTER",
            "domain_mappings": [
                {"source_dataset": "RAW_AE", "target_domain": "AE", "rationale": "Events"}
            ],
        }
    )
    payload = {
        "study_name": "SYN-FILTER",
        "datasets": [
            {
                "domain": "AE",
                "description": "Adverse events",
                "variables": [
                    {
                        "name": "AETERM",
                        "label": "Reported term",
                        "sources": [{"dataset": "RAW_AE", "variable": "AETERM"}],
                    }
                ],
            }
        ],
    }

    mapping = SDTMVariableMappingPlan.model_validate(payload)
    rule_payload = {
        "study_name": "SYN-FILTER",
        "record_plans": [{"target_domain": "AE", "record_plan": {
            "steps": [
                {"step_id": "read_ae", "operation": "read", "description": "Read events", "output": "ae_source", "source_dataset": "RAW_AE"},
                {"step_id": "filter_ae", "operation": "filter", "description": "Keep reported events", "output": "ae_filtered", "inputs": ["read_ae"], "condition": "AETERM is not null and trim(AETERM) != ''", "sas_condition": "not missing(AETERM)"},
            ],
            "output_step": "filter_ae",
        }}],
        "rule_augmentations": [{"rule_id": "AE-AETERM", "target_domain": "AE", "target_variable": "AETERM", "description": "Direct", "logic": "Direct", "r_expression": '.data[["AETERM"]]', "sas_expression": "AETERM"}],
    }
    invalid = SDTMRuleAugmentationPlan.model_validate(rule_payload)
    with pytest.raises(ValueError, match="AE record step filter_ae has an invalid executable R condition"):
        SDTMUseCase._validate_rule_batch("AE", mapping.datasets[0], domain_mapping.domain_mappings, invalid)

    rule_payload["record_plans"][0]["record_plan"]["steps"][1]["condition"] = (
        '!is.na(.data[["AETERM"]]) & trimws(.data[["AETERM"]]) != ""'
    )
    rule_payload["record_plans"][0]["record_plan"]["steps"][1]["sas_condition"] = "where not missing(AETERM)"
    invalid_sas = SDTMRuleAugmentationPlan.model_validate(rule_payload)
    with pytest.raises(ValueError, match="AE record step filter_ae has an invalid executable SAS condition"):
        SDTMUseCase._validate_rule_batch("AE", mapping.datasets[0], domain_mapping.domain_mappings, invalid_sas)

    rule_payload["record_plans"][0]["record_plan"]["steps"][1]["sas_condition"] = "not missing(AETERM)"
    valid = SDTMRuleAugmentationPlan.model_validate(rule_payload)
    SDTMUseCase._validate_rule_batch("AE", mapping.datasets[0], domain_mapping.domain_mappings, valid)


async def test_sdtm_prepare_review_ignores_legacy_record_plan_owned_by_rule_stage(tmp_path) -> None:
    edc = tmp_path / "edc.json"
    edc.write_text("{}", encoding="utf-8")
    source_spec = {
        "study_name": "SYN-LEGACY",
        "datasets": [
            {
                "name": "RAW_AE",
                "label": "Adverse events",
                "variables": [
                    {
                        "name": "AETERM",
                        "label": "Reported term",
                        "provenance": {"file": "edc.json"},
                    }
                ],
                "provenance": {"file": "edc.json"},
            }
        ],
    }
    domain_mapping = {
        "study_name": "SYN-LEGACY",
        "domain_mappings": [
            {"source_dataset": "RAW_AE", "target_domain": "AE", "rationale": "Events"}
        ],
    }
    variable_mapping = {
        "study_name": "SYN-LEGACY",
        "datasets": [
            {
                "domain": "AE",
                "description": "Adverse events",
                "record_plan": {
                    "steps": [
                        {
                            "step_id": "read_ae",
                            "operation": "read",
                            "description": "Read events",
                            "output": "ae_source",
                            "source_dataset": "RAW_AE",
                        },
                        {
                            "step_id": "filter_ae",
                            "operation": "filter",
                            "description": "Keep reported events",
                            "output": "ae_filtered",
                            "inputs": ["read_ae"],
                            "condition": "AETERM is not null",
                            "sas_condition": "not missing(AETERM)",
                        },
                    ],
                    "output_step": "filter_ae",
                },
                "variables": [
                    {
                        "name": "AETERM",
                        "label": "Reported term",
                        "sources": [{"dataset": "RAW_AE", "variable": "AETERM"}],
                    }
                ],
            }
        ],
    }

    review = await SDTMUseCase().prepare_review(
        UseCaseContext(
            inputs=[edc],
            options={
                "edc_source_spec": source_spec,
                "sdtm_domain_mapping": domain_mapping,
                "sdtm_variable_mapping": variable_mapping,
            },
            ai=SimpleNamespace(),
            settings=agent_settings(),
            agent_progress_path=tmp_path / "agent" / "progress.json",
        )
    )

    assert review is None


def test_sdtm_domain_revision_preserves_only_unchanged_variable_batches() -> None:
    previous = SDTMDomainMappingPlan.model_validate({
        "study_name": "SYN-101",
        "domain_mappings": [
            {"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "Demographics"},
            {"source_dataset": "RAW_AE", "target_domain": "AE", "rationale": "Adverse events"},
        ],
    })
    current = SDTMDomainMappingPlan.model_validate({
        "study_name": "SYN-101",
        "domain_mappings": [
            {"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "Updated wording only"},
            {"source_dataset": "RAW_AE", "target_domain": "DS", "rationale": "Disposition events"},
        ],
    })
    baseline = SDTMVariableMappingPlan.model_validate({
        "study_name": "SYN-101",
        "datasets": [
            {
                "domain": "DM", "description": "Demographics",
                "record_plan": read_plan("DM", "RAW_DM").model_dump(mode="json"),
                "review_assumptions": ["DM reviewed"],
                "variables": [{"name": "AGE", "label": "Age", "data_type": "Num", "sources": [{"dataset": "RAW_DM", "variable": "AGE"}]}],
            },
            {
                "domain": "AE", "description": "Adverse Events",
                "record_plan": read_plan("AE", "RAW_AE").model_dump(mode="json"),
                "review_unresolved_mappings": ["AE obsolete"],
                "variables": [{"name": "AETERM", "label": "Reported Term", "sources": [{"dataset": "RAW_AE", "variable": "AETERM"}]}],
            },
        ],
        "assumptions": ["DM reviewed"],
        "unresolved_mappings": ["AE obsolete"],
    })
    generated = SDTMVariableMappingPlan.model_validate({
        "study_name": "SYN-101",
        "datasets": [{
            "domain": "DS", "description": "Disposition",
            "record_plan": read_plan("DS", "RAW_AE").model_dump(mode="json"),
            "review_unresolved_mappings": ["DS review"],
            "variables": [{"name": "DSTERM", "label": "Reported Term", "sources": [{"dataset": "RAW_AE", "variable": "AETERM"}]}],
        }],
        "unresolved_mappings": ["DS review"],
    })

    reconciliation = SDTMUseCase.build_variable_mapping_reconciliation(previous, current, baseline)
    merged = SDTMUseCase.reconcile_variable_mapping(
        current,
        baseline=baseline,
        generated=generated,
        preserve_domains=reconciliation["preserve_domains"],
    )

    assert reconciliation["preserve_domains"] == ["DM"]
    assert reconciliation["regenerate_domains"] == ["DS"]
    assert [item.domain for item in merged.datasets] == ["DM", "DS"]
    assert merged.datasets[0].variables[0].name == "AGE"
    assert merged.assumptions == ["DM reviewed"]
    assert merged.unresolved_mappings == ["DS review"]


async def test_sdtm_unchanged_reopened_domain_plan_reuses_variable_mapping_without_model_call(tmp_path) -> None:
    source_spec = {
        "study_name": "SYN-101",
        "datasets": [{
            "name": "RAW_DM",
            "label": "Demographics",
            "variables": [{"name": "AGE", "label": "Age", "data_type": "integer", "provenance": {"file": "edc.json"}}],
            "provenance": {"file": "edc.json"},
        }],
    }
    domain_mapping = SDTMDomainMappingPlan.model_validate({
        "study_name": "SYN-101",
        "domain_mappings": [{"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "Demographics"}],
    })
    baseline = SDTMVariableMappingPlan.model_validate({
        "study_name": "SYN-101",
        "datasets": [{
            "domain": "DM", "description": "Demographics", "review_assumptions": ["Reviewed DM"],
            "record_plan": read_plan("DM", "RAW_DM").model_dump(mode="json"),
            "variables": [{"name": "AGE", "label": "Age", "data_type": "Num", "sources": [{"dataset": "RAW_DM", "variable": "AGE"}]}],
        }],
        "assumptions": ["Reviewed DM"],
    })
    reconciliation = SDTMUseCase.build_variable_mapping_reconciliation(domain_mapping, domain_mapping, baseline)
    completions = ScriptedCompletions([])
    settings = agent_settings(agent_max_turns=4)
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    edc = tmp_path / "edc.json"
    edc.write_text(json.dumps({"study": "SYN-101", "datasets": []}), encoding="utf-8")

    prepared = await SDTMUseCase().prepare_review(UseCaseContext(
        inputs=[edc],
        options={
            "edc_source_spec": source_spec,
            "sdtm_domain_mapping": domain_mapping.model_dump(mode="json"),
            "_sdtm_variable_mapping_reconcile": reconciliation,
        },
        ai=ai,
        settings=settings,
        agent_progress_path=tmp_path / "agent" / "progress.json",
    ))

    assert prepared is not None
    assert prepared.review_stage == "variable_mapping"
    assert prepared.value.variable_mapping.datasets[0].variables[0].name == "AGE"
    assert completions.requests == []


class FakeMessage:
    def __init__(self, call):
        self.content = None
        self.tool_calls = [call]

    def model_dump(self, **_):
        call = self.tool_calls[0]
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
            ],
        }


def tool_call(number: int, name: str, arguments: dict):
    return SimpleNamespace(
        id=f"call-{number}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class ScriptedCompletions:
    def __init__(self, actions):
        self.actions = list(actions)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        call = tool_call(len(self.requests), *self.actions.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(call))])


def agent_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "meta_api_key": "test-key",
        "meta_model": "test-model",
        "agent_max_turns": 8,
        "cdisc_mcp_enabled": False,
        "clinicalgov_mcp_enabled": False,
        "openfda_mcp_enabled": False,
        "bioportal_mcp_enabled": False,
        "pubmed_mcp_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_every_workflow_has_distinct_agent_instructions() -> None:
    assert set(AGENTS) == {
        "protocol-extraction",
        "clinical-document",
        "edc-design",
        "sdtm",
        "tlf",
    }
    assert len({agent.id for agent in AGENTS.values()}) == 5
    package_names = {
        "protocol-extraction": "protocol_extraction",
        "clinical-document": "clinical_document",
        "edc-design": "edc_design",
        "sdtm": "sdtm",
        "tlf": "tlf",
    }
    for agent in AGENTS.values():
        instructions = agent.instructions()
        assert "Call exactly one tool per turn" in instructions
        assert agent.workflow in get_agent(agent.workflow).workflow
        assert agent.instruction_file.name == "instructions.md"
        assert agent.instruction_file.parent.name == package_names[agent.workflow]


def test_every_protocol_agent_loads_the_shared_extraction_policy() -> None:
    agents = [get_agent("protocol-extraction"), *(definition for _, definition in PERSPECTIVE_AGENTS)]
    for agent in agents:
        instructions = agent.instructions()
        assert "# Shared clinical protocol extraction policy" in instructions
        assert "agreement among agents" in instructions
        assert agent.policy_files and agent.policy_files[0].name == "extraction_policy.md"


def test_every_sdtm_agent_loads_the_shared_mapping_policy() -> None:
    agents = [get_agent("sdtm"), SOURCE_NORMALIZATION_AGENT, *(definition for _, definition in STAGE_AGENTS)]
    for agent in agents:
        instructions = agent.instructions()
        assert "# Shared SDTM mapping policy" in instructions
        assert "specialist drafts as fallible observations" in instructions
        assert agent.policy_files and agent.policy_files[0].name == "mapping_policy.md"


async def test_agent_reads_contract_and_source_then_submits_valid_result(tmp_path) -> None:
    actions = [
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": {"study_title": "Synthetic Study"}}),
    ]
    completions = ScriptedCompletions(actions)
    settings = agent_settings()
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    progress_path = tmp_path / "agent" / "progress.json"

    outcome = await ClinicalAgentRunner(
        definition=get_agent("protocol-extraction"),
        result_model=StudySummary,
        ai=ai,
        settings=settings,
        progress_path=progress_path,
    ).run(objective="Extract the protocol", source="Synthetic protocol text", options={})

    assert outcome.value.study_title == "Synthetic Study"
    trace = json.loads(progress_path.read_text(encoding="utf-8"))
    assert trace["status"] == "completed"
    assert trace["read_source_chunks"] == [1]
    assert [event["name"] for event in trace["events"]] == [
        "inspect_workflow_contract",
        "read_source_chunk",
        "submit_result",
    ]
    assert trace["events"][0]["summary"].startswith("Reviewed the workflow contract")
    assert trace["events"][1]["input_summary"] == "Requested source chunk 1 of 1."
    assert trace["events"][1]["output_summary"] == "Reviewed source chunk 1; 0 chunk(s) remain."
    assert trace["events"][1]["intent"].startswith("Review source chunk 1")
    assert trace["events"][1]["input_details"] == {"Chunk requested": 1}
    assert trace["events"][1]["output_details"]["Chunks remaining"] == 0
    assert trace["events"][1]["evidence"] == ["Submitted source · chunk 1 of 1"]
    assert trace["events"][1]["duration_ms"] >= 1
    assert trace["events"][2]["output_summary"].endswith("was accepted.")
    assert trace["events"][2]["output_details"]["Schema validation"] == "Passed"
    assert "Synthetic protocol text" not in json.dumps(trace["events"])
    assert all(event.get("occurred_at") for event in trace["events"])
    first_tools = {item["function"]["name"] for item in completions.requests[0]["tools"]}
    assert first_tools == {"inspect_workflow_contract", "read_source_chunk", "submit_result"}
    assert completions.requests[0]["messages"][0]["role"] == "system"
    submit_tool = next(
        item for item in completions.requests[0]["tools"] if item["function"]["name"] == "submit_result"
    )
    submission_parameters = submit_tool["function"]["parameters"]
    assert "$defs" not in submission_parameters
    assert submission_parameters["properties"]["result"] == {
        "type": "object",
        "description": (
            "Complete structured result matching the exact schema returned by "
            "inspect_workflow_contract. Backend validation remains authoritative."
        ),
        "additionalProperties": True,
    }


async def test_agent_accepts_json_encoded_object_from_shallow_submit_tool(tmp_path) -> None:
    actions = [
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": json.dumps({"study_title": "Synthetic Study"})}),
    ]
    completions = ScriptedCompletions(actions)
    settings = agent_settings()
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outcome = await ClinicalAgentRunner(
        definition=get_agent("protocol-extraction"),
        result_model=StudySummary,
        ai=ai,
        settings=settings,
        progress_path=tmp_path / "progress.json",
    ).run(objective="Extract the protocol", source="Synthetic protocol text", options={})

    assert outcome.value.study_title == "Synthetic Study"


async def test_agent_returns_workflow_validator_problems_for_correction(tmp_path) -> None:
    actions = [
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": {"study_title": "Incomplete"}}),
        ("submit_result", {"result": {"study_title": "Corrected"}}),
    ]
    completions = ScriptedCompletions(actions)
    settings = agent_settings()
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    def validate_result(value) -> None:
        if value.study_title == "Incomplete":
            raise ValueError("A reviewed R and SAS condition is required.")

    progress_path = tmp_path / "progress.json"
    outcome = await ClinicalAgentRunner(
        definition=get_agent("protocol-extraction"),
        result_model=StudySummary,
        ai=ai,
        settings=settings,
        progress_path=progress_path,
        result_validator=validate_result,
    ).run(objective="Extract the protocol", source="Synthetic protocol text", options={})

    assert outcome.value.study_title == "Corrected"
    trace = json.loads(progress_path.read_text(encoding="utf-8"))
    rejected = trace["events"][2]
    assert rejected["ok"] is False
    assert rejected["error"] == "Result verification failed."
    tool_messages = [message for message in trace["messages"] if message["role"] == "tool"]
    assert "A reviewed R and SAS condition is required." in tool_messages[-2]["content"]


async def test_cdisc_dataset_tool_result_omits_navigation_links_without_losing_metadata(monkeypatch) -> None:
    variables = [
        {
            "name": f"LBVAR{index}",
            "label": f"Lab variable {index}",
            "description": "Complete variable metadata",
            "simpleDatatype": "Char",
            "core": "Exp",
            "_links": {"self": {"href": "https://library.example/" + "x" * 1_000}},
        }
        for index in range(62)
    ]
    raw_payload = {
        "ok": True,
        "result": {
            "result": {
                "name": "LB",
                "label": "Laboratory Test Results",
                "datasetVariables": variables,
                "_links": {"self": {"href": "https://library.example/datasets/LB"}},
            }
        },
    }

    async def fake_call(_clients, _call):
        return json.dumps(raw_payload)

    monkeypatch.setattr(MetaAIClient, "_call_mcp_tool", fake_call)
    settings = agent_settings()
    runner = ClinicalAgentRunner(
        definition=STAGE_AGENTS[1][1],
        result_model=SDTMVariableMappingPlan,
        ai=MetaAIClient(settings),
        settings=settings,
    )
    call = SimpleNamespace(function=SimpleNamespace(name="cdisc_get_dataset"))
    result = await runner._run_remote_tool(
        call,
        {"cdisc_get_dataset": SimpleNamespace()},
        {"contract_inspected": True, "remote_calls": 0},
    )

    dataset = result["result"]["result"]
    assert len(dataset["datasetVariables"]) == 62
    assert dataset["datasetVariables"][0]["description"] == "Complete variable metadata"
    assert "_links" not in json.dumps(result)
    assert result["reference_response"] == {
        "complete_metadata": True,
        "navigation_link_fields_omitted": 63,
    }
    assert len(json.dumps(result)) < len(json.dumps(raw_payload)) / 3


def test_sdtm_submit_tool_uses_shallow_provider_schema() -> None:
    settings = agent_settings()
    runner = ClinicalAgentRunner(
        definition=STAGE_AGENTS[1][1],
        result_model=SDTMVariableMappingPlan,
        ai=MetaAIClient(settings),
        settings=settings,
    )

    submit_tool = next(
        item
        for item in runner._internal_tool_definitions(3)
        if item["function"]["name"] == "submit_result"
    )
    parameters = submit_tool["function"]["parameters"]

    assert parameters["properties"]["result"]["type"] == "object"
    assert parameters["properties"]["result"]["additionalProperties"] is True
    assert "datasets" not in parameters["properties"]["result"].get("properties", {})
    assert "$defs" not in json.dumps(parameters)


async def test_agent_refuses_submission_until_every_source_chunk_is_read(tmp_path) -> None:
    actions = [
        ("inspect_workflow_contract", {}),
        ("submit_result", {"result": {"study_title": "Too early"}}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": {"study_title": "Supported"}}),
    ]
    completions = ScriptedCompletions(actions)
    settings = agent_settings()
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    progress_path = tmp_path / "progress.json"

    outcome = await ClinicalAgentRunner(
        definition=get_agent("protocol-extraction"),
        result_model=StudySummary,
        ai=ai,
        settings=settings,
        progress_path=progress_path,
    ).run(objective="Extract", source="One source chunk", options={})

    assert outcome.value.study_title == "Supported"
    trace = json.loads(progress_path.read_text(encoding="utf-8"))
    early_submit = trace["events"][1]
    assert early_submit["name"] == "submit_result"
    assert early_submit["ok"] is False
    assert "Read every source chunk" in early_submit["error"]


async def test_agent_fails_closed_before_model_call_when_complete_source_exceeds_capacity(
    tmp_path,
) -> None:
    completions = ScriptedCompletions([])
    settings = agent_settings(
        max_source_chunks=2,
        chunk_characters=20,
        agent_max_turns=8,
    )
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    progress_path = tmp_path / "progress.json"

    with pytest.raises(AIResponseError, match="No partial source was sent to the model"):
        await ClinicalAgentRunner(
            definition=get_agent("protocol-extraction"),
            result_model=StudySummary,
            ai=ai,
            settings=settings,
            progress_path=progress_path,
        ).run(
            objective="Extract",
            source="A" * 100,
            options={},
        )

    assert completions.requests == []
    trace = json.loads(progress_path.read_text(encoding="utf-8"))
    assert trace["status"] == "blocked"
    assert trace["total_source_chunks"] == 5
    assert trace["read_source_chunks"] == []
    assert trace["events"][-1]["name"] == "complete_source_gate"
    assert trace["events"][-1]["output_details"]["Partial model execution"] is False


async def test_agent_can_use_workflow_specific_complete_source_capacity(tmp_path) -> None:
    actions = [
        ("inspect_workflow_contract", {}),
        *[("read_source_chunk", {"index": index}) for index in range(1, 10)],
        ("submit_result", {"result": {"study_title": "Complete nine-chunk study"}}),
    ]
    completions = ScriptedCompletions(actions)
    settings = agent_settings(
        max_source_chunks=8,
        chunk_characters=10,
        agent_max_turns=12,
    )
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    progress_path = tmp_path / "progress.json"

    outcome = await ClinicalAgentRunner(
        definition=get_agent("protocol-extraction"),
        result_model=StudySummary,
        ai=ai,
        settings=settings,
        progress_path=progress_path,
        complete_source_chunk_limit=12,
    ).run(
        objective="Extract every chunk",
        source="A" * 90,
        options={},
    )

    assert outcome.value.study_title == "Complete nine-chunk study"
    trace = json.loads(progress_path.read_text(encoding="utf-8"))
    assert trace["status"] == "completed"
    assert trace["total_source_chunks"] == 9
    assert trace["read_source_chunks"] == list(range(1, 10))


async def test_agent_revision_preserves_trace_and_receives_human_guidance(tmp_path) -> None:
    completions = ScriptedCompletions([
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": {"study_title": "Revised Synthetic Study"}}),
    ])
    settings = agent_settings()
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    progress_path = tmp_path / "progress.json"
    progress_path.write_text(json.dumps({
        "turn": 4,
        "events": [{
            "turn": 4,
            "type": "user_feedback",
            "actor": "user",
            "summary": "Clarify the endpoint timing.",
        }],
    }), encoding="utf-8")

    outcome = await ClinicalAgentRunner(
        definition=get_agent("protocol-extraction"),
        result_model=StudySummary,
        ai=ai,
        settings=settings,
        progress_path=progress_path,
    ).run(
        objective="Revise the protocol extraction",
        source="Synthetic protocol text",
        options={
            "review_feedback": [{"stage": "Extraction", "message": "Clarify the endpoint timing."}],
            "_review_revision_result": {"study_title": "Initial Synthetic Study"},
        },
        stage="Extraction",
    )

    assert outcome.value.study_title == "Revised Synthetic Study"
    trace = json.loads(progress_path.read_text(encoding="utf-8"))
    assert trace["events"][0]["actor"] == "user"
    assert [event["turn"] for event in trace["events"][1:]] == [5, 6, 7]
    initial_prompt = completions.requests[0]["messages"][1]["content"]
    assert "HUMAN REVIEW GUIDANCE" in initial_prompt
    assert "Clarify the endpoint timing." in initial_prompt
    assert "Initial Synthetic Study" in initial_prompt


async def test_protocol_extraction_runs_parallel_perspectives_then_reconciles(
    tmp_path, monkeypatch
) -> None:
    source_path = tmp_path / "synthetic-protocol.md"
    source_path.write_text("# Synthetic protocol\nPrimary endpoint: response at Week 12.", encoding="utf-8")
    calls = []
    active_perspectives = 0
    max_active_perspectives = 0

    class FakeRunner:
        def __init__(self, *, definition, result_model, ai, settings, progress_path):
            self.definition = definition
            self.progress_path = progress_path

        async def run(self, *, objective, source, options):
            nonlocal active_perspectives, max_active_perspectives
            is_lead = self.definition.id == "clinical-protocol-extraction-agent"
            if not is_lead:
                active_perspectives += 1
                max_active_perspectives = max(max_active_perspectives, active_perspectives)
                await asyncio.sleep(0)
                active_perspectives -= 1
            calls.append(
                {
                    "id": self.definition.id,
                    "objective": objective,
                    "source": source,
                    "progress_path": self.progress_path,
                }
            )
            title = "Reconciled protocol" if is_lead else self.definition.name
            return AgentOutcome(value=StudySummary(study_title=title), warnings=[], events=[])

    monkeypatch.setattr("app.use_cases.protocol_extraction.ClinicalAgentRunner", FakeRunner)
    progress_path = tmp_path / "agent" / "progress.json"
    generated = await ProtocolExtractionUseCase().generate(
        UseCaseContext(
            inputs=[source_path],
            options={"deidentified_acknowledged": True},
            ai=SimpleNamespace(),
            settings=agent_settings(),
            agent_progress_path=progress_path,
        )
    )

    assert max_active_perspectives == 3
    assert [call["id"] for call in calls[-1:]] == ["clinical-protocol-extraction-agent"]
    assert {call["id"] for call in calls[:-1]} == {
        "protocol-design-endpoints-agent",
        "protocol-conduct-eligibility-agent",
        "protocol-safety-ambiguity-agent",
    }
    assert all(call["progress_path"].name.startswith("perspective-") for call in calls[:-1])
    assert calls[-1]["progress_path"] == progress_path
    assert "Protocol Design and Endpoints Specialist" in calls[-1]["objective"]
    assert "Protocol Conduct and Eligibility Specialist" in calls[-1]["objective"]
    assert "Protocol Safety and Ambiguity Specialist" in calls[-1]["objective"]
    assert generated.value.study_title == "Reconciled protocol"


def test_edc_agent_verification_rejects_broken_form_references() -> None:
    design = EDCDesign(
        study_name="Synthetic",
        visits=[EDCVisit(name="Baseline", forms=["MISSING"])],
        forms=[EDCForm(form_id="DM", name="Demographics", fields=[])],
    )

    assert verify_result("edc-design", design) == [
        "Visit Baseline references unknown form MISSING."
    ]


async def test_sdtm_use_case_normalizes_edc_for_review(tmp_path) -> None:
    source_result = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "name": "RAW_DM",
                "label": "Demographics",
                "key_variables": ["SUBJID"],
                "variables": [
                    {
                        "name": "SUBJID",
                        "label": "Subject identifier",
                        "data_type": "text",
                        "provenance": {"file": "edc.json"},
                    }
                ],
                "provenance": {"file": "edc.json"},
            }
        ],
    }
    completions = ScriptedCompletions([
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": source_result}),
    ])
    settings = agent_settings(agent_max_turns=4)
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    edc = tmp_path / "edc.json"
    edc.write_text(json.dumps({"study": "SYN-101", "forms": []}), encoding="utf-8")
    crf = tmp_path / "blank.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.drawString(50, 750, "Subject Identifier")
    pdf.save()

    prepared = await SDTMUseCase().prepare_review(
        UseCaseContext(
            inputs=[crf, edc],
            options={"languages": ["r"]},
            ai=ai,
            settings=settings,
            agent_progress_path=tmp_path / "agent" / "progress.json",
        )
    )

    assert prepared is not None
    assert prepared.review_stage == "edc_source"
    assert prepared.value.datasets[0].variables[0].name == "SUBJID"


async def test_sdtm_use_case_pauses_after_each_mapping_stage_before_code_generation(tmp_path) -> None:
    domain_result = {
        "study_name": "SYN-101",
        "domain_mappings": [
            {
                "source_dataset": "RAW_DM",
                "target_domain": "DM",
                "rationale": "Demographics source",
            }
        ],
    }
    variable_result = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "domain": "DM",
                "description": "Demographics",
                "record_plan": read_plan("DM", "RAW_DM").model_dump(mode="json"),
                "variables": [
                    {
                        "name": "AGE",
                        "label": "Age",
                        "data_type": "Num",
                        "sources": [{"dataset": "RAW_DM", "variable": "AGE"}],
                        "crf_source_label": None,
                    }
                ],
            }
        ],
    }
    final_result = {
        "study_name": "SYN-101",
        "record_plans": [
            {"target_domain": "DM", "record_plan": read_plan("DM", "RAW_DM").model_dump(mode="json")}
        ],
        "rule_augmentations": [
            {
                "rule_id": "DM-AGE",
                "target_domain": "DM",
                "target_variable": "AGE",
                "description": "Copy collected age",
                "logic": "Direct assignment",
                "r_expression": '.data[["AGE"]]',
                "sas_expression": "AGE",
            }
        ],
    }
    actions = [
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": domain_result}),
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": variable_result}),
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": final_result}),
    ]
    completions = ScriptedCompletions(actions)
    settings = agent_settings(agent_max_turns=4)
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    edc = tmp_path / "edc.json"
    edc.write_text(
        json.dumps({"study": "SYN-101", "datasets": [{"name": "RAW_DM", "fields": ["AGE"]}]}),
        encoding="utf-8",
    )
    progress_path = tmp_path / "agent" / "progress.json"
    source_spec = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "name": "RAW_DM",
                "label": "Demographics",
                "variables": [
                    {
                        "name": "AGE",
                        "label": "Age",
                        "data_type": "integer",
                        "provenance": {"file": "edc.json"},
                    }
                ],
                "provenance": {"file": "edc.json"},
            }
        ],
    }

    domain_review = await SDTMUseCase().prepare_review(
        UseCaseContext(
            inputs=[edc],
            options={"languages": ["r", "sas"], "edc_source_spec": source_spec},
            ai=ai,
            settings=settings,
            agent_progress_path=progress_path,
        )
    )
    assert domain_review is not None
    assert domain_review.review_stage == "domain_mapping"
    assert domain_review.value.domain_mapping.domain_mappings[0].target_domain == "DM"

    variable_review = await SDTMUseCase().prepare_review(
        UseCaseContext(
            inputs=[edc],
            options={
                "languages": ["r", "sas"],
                "edc_source_spec": source_spec,
                "sdtm_domain_mapping": domain_result,
            },
            ai=ai,
            settings=settings,
            agent_progress_path=progress_path,
        )
    )
    assert variable_review is not None
    assert variable_review.review_stage == "variable_mapping"
    assert variable_review.value.variable_mapping.datasets[0].variables[0].name == "AGE"

    approved_options = {
        "languages": ["r", "sas"],
        "edc_source_spec": source_spec,
        "sdtm_domain_mapping": domain_result,
        "sdtm_variable_mapping": variable_result,
    }
    assert await SDTMUseCase().prepare_review(
        UseCaseContext(inputs=[edc], options=approved_options, ai=ai, settings=settings)
    ) is None

    generated = await SDTMUseCase().generate(
        UseCaseContext(
            inputs=[edc],
            options=approved_options,
            ai=ai,
            settings=settings,
            agent_progress_path=progress_path,
        )
    )

    assert generated.value.rule_augmentations[0].rule_id == "DM-AGE"
    assert generated.value.datasets[0].record_plan == read_plan("DM", "RAW_DM")
    assert any("Blank CRF was not supplied" in warning for warning in generated.warnings)
    assert any("BLANK CRF NOT SUPPLIED" in json.dumps(request) for request in completions.requests)
    assert "# SDTM stage 3" in completions.requests[-3]["messages"][0]["content"]
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["stage"] == "Rule augmentation"
    assert progress["stage_index"] == 3
    assert progress["completed_stages"] == [
        "Domain mapping",
        "Variable & value-level mapping",
        "Rule augmentation",
    ]
    assert {event["stage"] for event in progress["events"]} == {
        "Domain mapping",
        "Variable & value-level mapping",
        "Rule augmentation",
    }


def test_sdtm_domain_inventory_is_complete_and_compact_for_large_source() -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-LARGE",
            "datasets": [
                {
                    "name": f"RAW_{dataset_index:02d}",
                    "label": f"Dataset {dataset_index:02d}",
                    "variables": [
                        {
                            "name": f"VAR_{variable_index:03d}",
                            "label": f"Variable {variable_index:03d}",
                            "provenance": {"file": "large.json"},
                        }
                        for variable_index in range(30)
                    ],
                    "provenance": {"file": "large.json"},
                }
                for dataset_index in range(68)
            ],
        }
    )

    source = SDTMUseCase._domain_mapping_source(source_spec, [])

    assert len(chunk_text(source, 12_000)) <= 8
    for dataset in source_spec.datasets:
        assert f'"name":"{dataset.name}"' in source
    assert "provenance" not in source


async def test_sdtm_variable_and_rule_mapping_are_batched_by_target_domain(
    tmp_path,
    monkeypatch,
) -> None:
    source_spec = EDCSourceSpecification.model_validate(
        {
            "study_name": "SYN-BATCH",
            "datasets": [
                {
                    "name": "RAW_DM",
                    "label": "Demographics",
                    "variables": [
                        {"name": "AGE", "label": "Age", "provenance": {"file": "edc.json"}}
                    ],
                    "provenance": {"file": "edc.json"},
                },
                {
                    "name": "RAW_AE",
                    "label": "Adverse events",
                    "variables": [
                        {
                            "name": "AETERM",
                            "label": "Reported term",
                            "provenance": {"file": "edc.json"},
                        }
                    ],
                    "provenance": {"file": "edc.json"},
                },
            ],
        }
    )
    domain_mapping = SDTMDomainMappingPlan.model_validate(
        {
            "study_name": "SYN-BATCH",
            "domain_mappings": [
                {"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "DM source"},
                {"source_dataset": "RAW_AE", "target_domain": "AE", "rationale": "AE source"},
            ],
        }
    )
    calls: list[dict] = []
    variable_active = 0
    variable_peak = 0

    class FakeVariableRunner:
        def __init__(self, *, progress_path, complete_source_chunk_limit, **_):
            self.progress_path = progress_path
            self.complete_source_chunk_limit = complete_source_chunk_limit

        async def run(self, *, objective, source, prior_events=None, **_):
            nonlocal variable_active, variable_peak
            target = "DM" if "target DM" in objective else "AE"
            source_dataset = "RAW_DM" if target == "DM" else "RAW_AE"
            source_field = "AGE" if target == "DM" else "AETERM"
            calls.append({
                "target": target,
                "source": source,
                "progress_path": self.progress_path,
                "complete_source_chunk_limit": self.complete_source_chunk_limit,
            })
            variable_active += 1
            variable_peak = max(variable_peak, variable_active)
            try:
                await asyncio.sleep(0.02)
                return AgentOutcome(
                    value=SDTMVariableMappingPlan.model_validate(
                        {
                            "study_name": "SYN-BATCH",
                            "datasets": [
                                {
                                    "domain": target,
                                    "description": target,
                                    "record_plan": read_plan(target, source_dataset).model_dump(mode="json"),
                                    "variables": [
                                        {
                                            "name": source_field,
                                            "label": source_field,
                                            "sources": [{"dataset": source_dataset, "variable": source_field}],
                                        }
                                    ],
                                }
                            ],
                            "assumptions": [f"{target} batch assumption"],
                            "unresolved_mappings": [f"{target} batch decision"],
                        }
                    ),
                    warnings=[],
                    events=[*(prior_events or []), {"turn": len(calls), "stage": "variable"}],
                )
            finally:
                variable_active -= 1

    monkeypatch.setattr("app.use_cases.sdtm.ClinicalAgentRunner", FakeVariableRunner)
    use_case = SDTMUseCase()
    variable_mapping, _ = await use_case._generate_variable_mapping_batches(
        UseCaseContext(
            inputs=[],
            options={},
            ai=SimpleNamespace(),
            settings=agent_settings(sdtm_domain_agent_concurrency=2),
            agent_progress_path=tmp_path / "progress.json",
        ),
        source_spec=source_spec,
        domain_mapping=domain_mapping,
        context_inputs=[],
        crf=None,
        agent_options={},
        stage_count=3,
    )

    assert [dataset.domain for dataset in variable_mapping.datasets] == ["DM", "AE"]
    assert variable_mapping.datasets[0].review_assumptions == ["DM batch assumption"]
    assert variable_mapping.datasets[1].review_unresolved_mappings == ["AE batch decision"]
    assert variable_peak == 2
    assert {call["target"] for call in calls} == {"DM", "AE"}
    assert len({call["progress_path"] for call in calls}) == 2
    assert {call["complete_source_chunk_limit"] for call in calls} == {12}
    calls_by_target = {call["target"]: call for call in calls}
    assert '"name":"RAW_AE"' not in calls_by_target["DM"]["source"]
    assert '"name":"RAW_DM"' not in calls_by_target["AE"]["source"]

    rule_calls: list[dict] = []
    rule_active = 0
    rule_peak = 0

    class FakeRuleRunner:
        def __init__(self, *, progress_path, complete_source_chunk_limit, **_):
            self.progress_path = progress_path
            self.complete_source_chunk_limit = complete_source_chunk_limit

        async def run(self, *, objective, source, prior_events=None, **_):
            nonlocal rule_active, rule_peak
            target = "DM" if "target DM" in objective else "AE"
            variable = "AGE" if target == "DM" else "AETERM"
            rule_calls.append({
                "target": target,
                "source": source,
                "progress_path": self.progress_path,
                "complete_source_chunk_limit": self.complete_source_chunk_limit,
            })
            rule_active += 1
            rule_peak = max(rule_peak, rule_active)
            try:
                await asyncio.sleep(0.02)
                return AgentOutcome(
                    value=SDTMRuleAugmentationPlan.model_validate(
                        {
                            "study_name": "SYN-BATCH",
                            "record_plans": [
                                {"target_domain": target, "record_plan": read_plan(target, f"RAW_{target}").model_dump(mode="json")}
                            ],
                            "rule_augmentations": [
                                {
                                    "rule_id": f"{target}-{variable}",
                                    "target_domain": target,
                                    "target_variable": variable,
                                    "description": "Direct",
                                    "logic": "Direct",
                                    "r_expression": f'.data[["{variable}"]] ',
                                    "sas_expression": variable,
                                }
                            ],
                        }
                    ),
                    warnings=[],
                    events=[*(prior_events or []), {"turn": len(rule_calls), "stage": "rule"}],
                )
            finally:
                rule_active -= 1

    monkeypatch.setattr("app.use_cases.sdtm.ClinicalAgentRunner", FakeRuleRunner)
    rule_plan, _ = await use_case._generate_rule_batches(
        UseCaseContext(
            inputs=[],
            options={"edc_source_spec": source_spec.model_dump(mode="json")},
            ai=SimpleNamespace(),
            settings=agent_settings(sdtm_domain_agent_concurrency=2),
            agent_progress_path=tmp_path / "progress.json",
        ),
        domain_mapping=domain_mapping,
        variable_mapping=variable_mapping,
    )

    assert [rule.target_domain for rule in rule_plan.rule_augmentations] == ["DM", "AE"]
    assert rule_peak == 2
    assert {call["target"] for call in rule_calls} == {"DM", "AE"}
    assert len({call["progress_path"] for call in rule_calls}) == 2
    assert {call["complete_source_chunk_limit"] for call in rule_calls} == {12}
    rule_calls_by_target = {call["target"]: call for call in rule_calls}
    assert '"domain":"AE"' not in rule_calls_by_target["DM"]["source"]
    assert '"domain":"DM"' not in rule_calls_by_target["AE"]["source"]


async def test_sdtm_parallel_domain_agents_retry_only_transiently_failed_domain(tmp_path) -> None:
    progress_path = tmp_path / "agent" / "progress.json"
    attempts = {"DM": 0, "LB": 0}

    async def generate(domain: str, path) -> AgentOutcome:
        attempts[domain] += 1
        prior = {}
        if path is not None and path.is_file():
            prior = json.loads(path.read_text(encoding="utf-8"))
        events = [event for event in prior.get("events", []) if isinstance(event, dict)]
        if domain == "LB" and attempts[domain] == 1:
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({
                    "status": "paused",
                    "turn": 1,
                    "stage": "Variable & value-level mapping",
                    "events": events,
                    "error": "Model API call failed: Request timed out.",
                }), encoding="utf-8")
            raise TimeoutError("Request timed out.")
        now = f"2026-11-01T15:2{attempts[domain]}:00+00:00"
        events.append({
            "turn": max([int(item.get("turn", 0)) for item in events] or [0]) + 1,
            "type": "tool",
            "name": "submit_result",
            "summary": "Submitted mapping",
            "occurred_at": now,
        })
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "status": "completed",
                "turn": events[-1]["turn"],
                "stage": "Variable & value-level mapping",
                "events": events,
                "updated_at": now,
                "completed_at": now,
            }), encoding="utf-8")
        return AgentOutcome(value=StudySummary(study_title=domain), warnings=[], events=events)

    outcomes = await SDTMUseCase()._run_parallel_domain_agents(
        UseCaseContext(
            inputs=[],
            options={},
            ai=SimpleNamespace(),
            settings=agent_settings(
                sdtm_domain_agent_concurrency=2,
                sdtm_domain_agent_max_attempts=2,
            ),
            agent_progress_path=progress_path,
        ),
        target_domains=["DM", "LB"],
        stage="Variable & value-level mapping",
        stage_index=2,
        stage_count=3,
        completed_stages=["Domain mapping"],
        generate=generate,
    )

    assert [outcome.value.study_title for outcome in outcomes] == ["DM", "LB"]
    assert attempts == {"DM": 1, "LB": 2}
    merged = json.loads(progress_path.read_text(encoding="utf-8"))
    retry = next(event for event in merged["events"] if event["type"] == "domain_retry")
    assert retry["input_details"]["Target domain"] == "LB"
    assert retry["output_details"]["Other domain results retained"] is True
    assert {item["domain"]: item["status"] for item in merged["domain_agents"]} == {
        "DM": "completed",
        "LB": "completed",
    }


def test_sdtm_domain_retry_recognizes_timeout_nested_in_task_group() -> None:
    wrapped = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("domain request failed")],
    )
    wrapped.exceptions[0].__cause__ = TimeoutError("Request timed out.")

    assert SDTMUseCase._is_retryable_domain_error(wrapped) is True
    assert SDTMUseCase._is_retryable_domain_error(
        ExceptionGroup("unhandled errors in a TaskGroup", [ValueError("invalid mapping")])
    ) is False


async def test_completed_variable_domain_rerun_also_refreshes_only_its_rules(tmp_path, monkeypatch) -> None:
    source_spec = EDCSourceSpecification.model_validate({
        "study_name": "SYN-RERUN",
        "datasets": [
            {"name": "RAW_DM", "label": "Demographics", "variables": [{"name": "AGE", "label": "Age", "provenance": {"file": "edc.json"}}], "provenance": {"file": "edc.json"}},
            {"name": "RAW_AE", "label": "Adverse events", "variables": [{"name": "AETERM", "label": "Term", "provenance": {"file": "edc.json"}}], "provenance": {"file": "edc.json"}},
        ],
    })
    baseline = SDTMPlan.model_validate({
        "study_name": "SYN-RERUN",
        "domain_mappings": [
            {"source_dataset": "RAW_DM", "target_domain": "DM", "rationale": "DM source"},
            {"source_dataset": "RAW_AE", "target_domain": "AE", "rationale": "AE source"},
        ],
        "datasets": [
            {"domain": "DM", "description": "DM", "record_plan": read_plan("DM", "RAW_DM"), "variables": [{"name": "AGE", "label": "Age", "sources": [source("RAW_DM", "AGE")]}]},
            {"domain": "AE", "description": "AE", "record_plan": read_plan("AE", "RAW_AE"), "variables": [{"name": "AETERM", "label": "Term", "sources": [source("RAW_AE", "AETERM")], "mapping_expression": "Old mapping"}]},
        ],
        "rule_augmentations": [
            {"rule_id": "DM-AGE", "target_domain": "DM", "target_variable": "AGE", "description": "DM rule", "logic": "Direct", "r_expression": '.data[["AGE"]]', "sas_expression": "AGE"},
            {"rule_id": "AE-AETERM", "target_domain": "AE", "target_variable": "AETERM", "description": "Old AE rule", "logic": "Direct", "r_expression": '.data[["AETERM"]]', "sas_expression": "AETERM"},
        ],
    })
    generated_ae = SDTMVariableMappingPlan.model_validate({
        "study_name": "SYN-RERUN",
        "datasets": [{
            "domain": "AE", "description": "AE", "record_plan": read_plan("AE", "RAW_AE"),
            "variables": [{"name": "AETERM", "label": "Term", "sources": [source("RAW_AE", "AETERM")], "mapping_expression": "Updated mapping"}],
        }],
    })
    calls: list[str] = []

    async def fake_variables(*_args, **kwargs):
        assert kwargs["target_domains"] == ["AE"]
        calls.append("variables")
        return generated_ae, []

    async def fake_rules(*_args, **kwargs):
        assert kwargs["target_domains"] == ["AE"]
        variable_mapping = kwargs["variable_mapping"]
        retained_dm = next(item for item in variable_mapping.datasets if item.domain == "DM")
        assert retained_dm.variables == baseline.datasets[0].variables
        assert next(item for item in variable_mapping.datasets if item.domain == "AE").variables[0].mapping_expression == "Updated mapping"
        calls.append("rules")
        return SDTMRuleAugmentationPlan.model_validate({
            "study_name": "SYN-RERUN",
            "record_plans": [{"target_domain": "AE", "record_plan": read_plan("AE", "RAW_AE")}],
            "rule_augmentations": [{"rule_id": "AE-AETERM", "target_domain": "AE", "target_variable": "AETERM", "description": "Updated AE rule", "logic": "Normalize", "r_expression": 'trimws(.data[["AETERM"]])', "sas_expression": "strip(AETERM)"}],
        }), []

    use_case = SDTMUseCase()
    monkeypatch.setattr(use_case, "_generate_variable_mapping_batches", fake_variables)
    monkeypatch.setattr(use_case, "_generate_rule_batches", fake_rules)
    edc_path = tmp_path / "edc.json"
    edc_path.write_text(source_spec.model_dump_json(), encoding="utf-8")
    generated = await use_case.regenerate_completed_domain(
        UseCaseContext(
            inputs=[edc_path],
            options={"edc_source_spec": source_spec.model_dump(mode="json")},
            ai=SimpleNamespace(),
            settings=agent_settings(),
        ),
        baseline=baseline,
        stage="variable_mapping",
        target_domain="AE",
    )

    proposed = generated.value
    assert calls == ["variables", "rules"]
    assert proposed.datasets[0] == baseline.datasets[0]
    assert proposed.datasets[1].variables[0].mapping_expression == "Updated mapping"
    assert proposed.rule_augmentations[0] == baseline.rule_augmentations[0]
    assert proposed.rule_augmentations[1].description == "Updated AE rule"


def test_sdtm_parallel_domain_progress_merges_isolated_traces(tmp_path) -> None:
    progress_path = tmp_path / "agent" / "progress.json"
    domain_directory = progress_path.parent / "domains" / "variable-value-level-mapping"
    domain_directory.mkdir(parents=True)
    domain_paths = {
        "DM": domain_directory / "001-dm.json",
        "AE": domain_directory / "002-ae.json",
    }
    for domain, occurred_at in (
        ("DM", "2026-10-31T12:00:02+00:00"),
        ("AE", "2026-10-31T12:00:01+00:00"),
    ):
        domain_paths[domain].write_text(
            json.dumps(
                {
                    "status": "completed",
                    "turn": 3,
                    "total_source_chunks": 2,
                    "read_source_chunks": [1, 2],
                    "started_at": "2026-10-31T12:00:00+00:00",
                    "updated_at": occurred_at,
                    "events": [
                        {
                            "turn": 3,
                            "type": "tool",
                            "name": "submit_result",
                            "summary": "Submitted mapping",
                            "occurred_at": occurred_at,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    SDTMUseCase._merge_domain_progress(
        progress_path,
        baseline={
            "turn": 5,
            "max_turns": 20,
            "events": [{"turn": 5, "type": "tool", "summary": "Approved domain mapping"}],
        },
        target_domains=["DM", "AE"],
        domain_paths=domain_paths,
        stage="Variable & value-level mapping",
        stage_index=2,
        stage_count=3,
        completed_stages=["Domain mapping"],
        model="test-model",
        max_turns_per_domain=8,
        status="completed",
    )

    merged = json.loads(progress_path.read_text(encoding="utf-8"))
    assert merged["status"] == "completed"
    assert merged["completed_stages"] == ["Domain mapping", "Variable & value-level mapping"]
    assert merged["total_source_chunks"] == 4
    assert merged["read_source_chunks"] == [1, 2, 3, 4]
    assert [event["turn"] for event in merged["events"]] == [5, 6, 7]
    assert [event["summary"] for event in merged["events"][1:]] == [
        "AE: Submitted mapping",
        "DM: Submitted mapping",
    ]
    assert [event["input_details"]["Target domain"] for event in merged["events"][1:]] == ["AE", "DM"]
    assert {item["domain"] for item in merged["domain_agents"]} == {"DM", "AE"}


async def test_tlf_use_case_pauses_after_inventory_shell_and_programming(tmp_path) -> None:
    inventory = {
        "study_name": "SYN-101",
        "outputs": [{"output_id": "T-01", "output_type": "table", "title": "Change from baseline"}],
    }
    analysis = {
        "study_name": "SYN-101",
        "outputs": [{
            "output_id": "T-01",
            "output_type": "table",
            "title": "Change from baseline",
            "population": "Intent-to-Treat",
            "population_filter": "ADSL.ITTFL = 'Y'",
            "analysis_datasets": ["ADSL", "ADEFF"],
            "source_variables": [{"dataset": "ADEFF", "variable": "CHG"}],
            "treatment_variable": "ADSL.TRT01P",
            "analysis_method": "ANCOVA",
            "columns": [{"column_id": "TRT", "heading": "Treatment", "source": "ADSL.TRT01P", "format": "text"}],
            "rows": [{"row_id": "LSMEAN", "label": "LS mean change", "source": "ADEFF.CHG", "statistic": "LS mean", "format": "8.2"}],
            "source_reference": "SAP efficacy analysis",
            "readiness": "ready",
        }],
    }
    programming = {
        "study_name": "SYN-101",
        "programs": [{
            "output_id": "T-01",
            "input_datasets": ["ADSL", "ADEFF"],
            "adam_sources": [{"dataset": "ADEFF", "variable": "CHG"}],
            "derivation_steps": ["Join ADSL and ADEFF", "Fit ANCOVA"],
            "r_code": "fit <- lm(CHG ~ TRT01P + BASE, data = adeff)",
            "sas_code": "proc glm data=adeff; model chg=trt01p base; run;",
        }],
    }
    actions = []
    for result in (inventory, analysis, programming):
        actions.extend([
            ("inspect_workflow_contract", {}),
            ("read_source_chunk", {"index": 1}),
            ("submit_result", {"result": result}),
        ])
    completions = ScriptedCompletions(actions)
    settings = agent_settings(agent_max_turns=4)
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    sap = tmp_path / "sap.md"
    sap.write_text("Analyze Week 12 change from baseline in the ITT population using ANCOVA.", encoding="utf-8")
    progress_path = tmp_path / "agent" / "progress.json"

    use_case = TLFUseCase()
    inventory_review = await use_case.prepare_review(UseCaseContext(inputs=[sap], options={"languages": ["r", "sas"]}, ai=ai, settings=settings, agent_progress_path=progress_path))
    assert inventory_review is not None
    assert inventory_review.review_stage == "tlf_inventory"
    assert "conventional clinical-study TLF package" in json.dumps(completions.requests[:3])

    inventory_options = {
        "languages": ["r", "sas"],
        "tlf_inventory_plan": inventory_review.value.model_dump(mode="json"),
    }
    shell_review = await use_case.prepare_review(UseCaseContext(inputs=[sap], options=inventory_options, ai=ai, settings=settings, agent_progress_path=progress_path))
    assert shell_review is not None
    assert shell_review.review_stage == "tlf_shell"
    assert shell_review.value.outputs[0].output_id == "T-01"

    shell_options = {
        **inventory_options,
        "tlf_shell_plan": shell_review.value.model_dump(mode="json"),
    }
    programming_review = await use_case.prepare_review(UseCaseContext(inputs=[sap], options=shell_options, ai=ai, settings=settings, agent_progress_path=progress_path))
    assert programming_review is not None
    assert programming_review.review_stage == "tlf_programming"
    assert programming_review.value.programs[0].adam_sources[0].variable == "CHG"

    generated = await use_case.generate(UseCaseContext(inputs=[sap], options={**shell_options, "tlf_programming_plan": programming_review.value.model_dump(mode="json")}, ai=ai, settings=settings, agent_progress_path=progress_path))

    assert generated.value.programs[0].output_id == "T-01"
    assert generated.value.outputs[0].readiness == "ready"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["stage"] == "Programming augmentation"
    assert progress["completed_stages"] == ["Output inventory", "Analysis & display specification", "Programming augmentation"]


def test_tlf_inventory_tracks_source_supported_and_conventional_proposals() -> None:
    plan = TLFInventoryPlan.model_validate({
        "study_name": "SYN-101",
        "outputs": [
            {
                "output_id": "T-01",
                "output_type": "table",
                "title": "Primary efficacy analysis",
                "basis": "source_supported",
            },
            {
                "output_id": "T-02",
                "output_type": "table",
                "title": "Demographics and baseline characteristics",
                "basis": "conventional_proposal",
                "source_reference": "CONVENTIONAL PROPOSAL — not specified in the SAP",
            },
        ],
    })

    assert plan.outputs[0].basis == "source_supported"
    assert plan.outputs[1].basis == "conventional_proposal"
