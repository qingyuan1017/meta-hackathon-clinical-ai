import json
from types import SimpleNamespace

from app.agents import AGENTS, ClinicalAgentRunner, get_agent
from app.agents.runtime import verify_result
from app.ai import MetaAIClient
from app.config import Settings
from app.schemas import EDCDesign, EDCForm, EDCVisit, StudySummary


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
    for agent in AGENTS.values():
        instructions = agent.instructions()
        assert "Call exactly one tool per turn" in instructions
        assert agent.workflow in get_agent(agent.workflow).workflow


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


def test_edc_agent_verification_rejects_broken_form_references() -> None:
    design = EDCDesign(
        study_name="Synthetic",
        visits=[EDCVisit(name="Baseline", forms=["MISSING"])],
        forms=[EDCForm(form_id="DM", name="Demographics", fields=[])],
    )

    assert verify_result("edc-design", design) == [
        "Visit Baseline references unknown form MISSING."
    ]
