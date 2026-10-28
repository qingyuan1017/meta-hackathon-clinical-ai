import asyncio
import json
from types import SimpleNamespace

from app.agents import AGENTS, AgentOutcome, ClinicalAgentRunner, get_agent
from app.agents.protocol_extraction import PERSPECTIVE_AGENTS
from app.agents.sdtm import STAGE_AGENTS
from reportlab.pdfgen import canvas

from app.agents.runtime import verify_result
from app.ai import MetaAIClient
from app.config import Settings
from app.schemas import EDCDesign, EDCForm, EDCVisit, StudySummary
from app.use_cases.base import UseCaseContext
from app.use_cases.protocol_extraction import ProtocolExtractionUseCase
from app.use_cases.sdtm import SDTMUseCase


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
    agents = [get_agent("sdtm"), *(definition for _, definition in STAGE_AGENTS)]
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


async def test_sdtm_use_case_runs_three_ordered_mapping_stages(tmp_path) -> None:
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
                        "crf_source_label": "Age",
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
    lead_result = {
        "study_name": "SYN-101",
        "domain_mappings": domain_result["domain_mappings"],
        "datasets": variable_result["datasets"],
        "domain_rule_augmentations": final_result["domain_rule_augmentations"],
        "rule_augmentations": final_result["rule_augmentations"],
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
        ("inspect_workflow_contract", {}),
        ("read_source_chunk", {"index": 1}),
        ("submit_result", {"result": lead_result}),
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
    crf = tmp_path / "blank.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.drawString(50, 750, "Age")
    pdf.save()
    progress_path = tmp_path / "agent" / "progress.json"

    generated = await SDTMUseCase().generate(
        UseCaseContext(
            inputs=[crf, edc],
            options={"languages": ["r", "sas"]},
            ai=ai,
            settings=settings,
            agent_progress_path=progress_path,
        )
    )

    assert generated.value.rule_augmentations[0].rule_id == "DM-AGE"
    assert "# SDTM mapping lead" in completions.requests[-3]["messages"][0]["content"]
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
