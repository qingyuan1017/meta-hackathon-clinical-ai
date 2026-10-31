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
                "variables": [
                    {
                        "name": "STUDYID",
                        "label": "Study Identifier",
                        "source_dataset": None,
                        "source_field": None,
                        "origin": "Assigned",
                        "mapping_expression": "Assign the approved study identifier SYN-ASSIGNED.",
                    },
                    {
                        "name": "SUBJID",
                        "label": "Subject Identifier",
                        "source_dataset": "RAW_DM",
                        "source_field": "SUBJID",
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
    invalid_payload["datasets"][0]["variables"][0]["source_dataset"] = "Assigned"
    invalid_payload["datasets"][0]["variables"][0]["source_field"] = "STUDYID"
    invalid = SDTMVariableMappingPlan.model_validate(invalid_payload)
    with pytest.raises(ValueError, match="unknown source dataset Assigned"):
        SDTMUseCase.validate_variable_mapping(source_spec, domain_mapping, invalid)


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
    assert "$defs" in submit_tool["function"]["parameters"]
    assert "$defs" not in submit_tool["function"]["parameters"]["properties"]["result"]


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
                "variables": [
                    {
                        "name": "AGE",
                        "label": "Age",
                        "data_type": "Num",
                        "source_dataset": "RAW_DM",
                        "source_field": "AGE",
                        "crf_source_label": None,
                    }
                ],
            }
        ],
    }
    final_result = {
        "study_name": "SYN-101",
        "domain_rule_augmentations": [
            {
                "rule_id": "DM-SOURCE",
                "target_domain": "DM",
                "source_datasets": ["RAW_DM"],
                "description": "Use demographics source",
                "logic": "Read the raw demographics dataset",
                "r_input_expression": "raw_dm",
                "sas_input_statement": "set raw.raw_dm;",
            }
        ],
        "rule_augmentations": [
            {
                "rule_id": "DM-AGE",
                "target_domain": "DM",
                "target_variable": "AGE",
                "source_dependencies": ["RAW_DM.AGE"],
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

    class FakeVariableRunner:
        def __init__(self, **_):
            pass

        async def run(self, *, objective, source, prior_events=None, **_):
            target = "DM" if "target DM" in objective else "AE"
            source_dataset = "RAW_DM" if target == "DM" else "RAW_AE"
            source_field = "AGE" if target == "DM" else "AETERM"
            calls.append({"target": target, "source": source})
            return AgentOutcome(
                value=SDTMVariableMappingPlan.model_validate(
                    {
                        "study_name": "SYN-BATCH",
                        "datasets": [
                            {
                                "domain": target,
                                "description": target,
                                "variables": [
                                    {
                                        "name": source_field,
                                        "label": source_field,
                                        "source_dataset": source_dataset,
                                        "source_field": source_field,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                warnings=[],
                events=[*(prior_events or []), {"turn": len(calls), "stage": "variable"}],
            )

    monkeypatch.setattr("app.use_cases.sdtm.ClinicalAgentRunner", FakeVariableRunner)
    use_case = SDTMUseCase()
    variable_mapping, _ = await use_case._generate_variable_mapping_batches(
        UseCaseContext(
            inputs=[],
            options={},
            ai=SimpleNamespace(),
            settings=agent_settings(),
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
    assert [call["target"] for call in calls] == ["DM", "AE"]
    assert '"name":"RAW_AE"' not in calls[0]["source"]
    assert '"name":"RAW_DM"' not in calls[1]["source"]

    rule_calls: list[dict] = []

    class FakeRuleRunner:
        def __init__(self, **_):
            pass

        async def run(self, *, objective, source, prior_events=None, **_):
            target = "DM" if "target DM" in objective else "AE"
            source_dataset = "RAW_DM" if target == "DM" else "RAW_AE"
            variable = "AGE" if target == "DM" else "AETERM"
            rule_calls.append({"target": target, "source": source})
            return AgentOutcome(
                value=SDTMRuleAugmentationPlan.model_validate(
                    {
                        "study_name": "SYN-BATCH",
                        "domain_rule_augmentations": [
                            {
                                "rule_id": f"{target}-SOURCE",
                                "target_domain": target,
                                "source_datasets": [source_dataset],
                                "description": "Prepare source",
                                "logic": "Direct",
                                "r_input_expression": source_dataset.lower(),
                                "sas_input_statement": f"set raw.{source_dataset.lower()};",
                            }
                        ],
                        "rule_augmentations": [
                            {
                                "rule_id": f"{target}-{variable}",
                                "target_domain": target,
                                "target_variable": variable,
                                "source_dependencies": [f"{source_dataset}.{variable}"],
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

    monkeypatch.setattr("app.use_cases.sdtm.ClinicalAgentRunner", FakeRuleRunner)
    rule_plan, _ = await use_case._generate_rule_batches(
        UseCaseContext(
            inputs=[],
            options={},
            ai=SimpleNamespace(),
            settings=agent_settings(),
            agent_progress_path=tmp_path / "progress.json",
        ),
        domain_mapping=domain_mapping,
        variable_mapping=variable_mapping,
    )

    assert [rule.target_domain for rule in rule_plan.domain_rule_augmentations] == ["DM", "AE"]
    assert [call["target"] for call in rule_calls] == ["DM", "AE"]
    assert '"domain":"AE"' not in rule_calls[0]["source"]
    assert '"domain":"DM"' not in rule_calls[1]["source"]


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
