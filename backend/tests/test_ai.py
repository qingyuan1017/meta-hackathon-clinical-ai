import pytest
from types import SimpleNamespace

from app.ai import MetaAIClient
from app.config import Settings


def test_decode_json_accepts_fenced_content() -> None:
    assert MetaAIClient._decode_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_decode_json_rejects_array() -> None:
    with pytest.raises(ValueError):
        MetaAIClient._decode_json("[1, 2]")


async def test_meta_client_executes_remote_clinicalgov_mcp_tool_call(monkeypatch) -> None:
    tools = [
        SimpleNamespace(
            name=name,
            description=f"Description for {name}",
            input_schema={"type": "object", "properties": {}},
        )
        for name in (
            "clinicalgov_search_studies",
            "clinicalgov_get_study",
            "clinicalgov_get_api_info",
            "clinicalgov_read_endpoint",
        )
    ]

    class FakeMCPClient:
        def __init__(self, url: str):
            assert url == "http://clinicalgov.test/mcp"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=tools)

        async def call_tool(self, name: str, arguments: dict):
            assert name == "clinicalgov_search_studies"
            assert arguments == {"condition": "asthma", "page_size": 1}
            return SimpleNamespace(
                is_error=False,
                structured_content={
                    "studies": [
                        {
                            "protocolSection": {
                                "identificationModule": {
                                    "nctId": "NCT01234567",
                                    "briefTitle": "Synthetic asthma study",
                                }
                            }
                        }
                    ]
                },
                content=[],
            )

    class FakeMessage:
        def __init__(self, *, content=None, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

        def model_dump(self, **_):
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
                    for call in self.tool_calls or []
                ],
            }

    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="clinicalgov_search_studies",
            arguments='{"condition":"asthma","page_size":1}',
        ),
    )
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(tool_calls=[tool_call]))]),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=FakeMessage(content='{"answer":"NCT01234567"}', tool_calls=None)
                )
            ]
        ),
    ]

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return responses.pop(0)

    completions = FakeCompletions()
    settings = Settings(
        _env_file=None,
        meta_api_key="test-key",
        meta_model="test-model",
        clinicalgov_mcp_enabled=True,
        clinicalgov_mcp_url="http://clinicalgov.test/mcp",
    )
    ai = MetaAIClient(settings)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr("app.ai.MCPClient", FakeMCPClient)

    result = await ai._complete([{"role": "user", "content": "Find an asthma study"}])

    assert result == '{"answer":"NCT01234567"}'
    assert {tool["function"]["name"] for tool in completions.calls[0]["tools"]} == {
        "clinicalgov_search_studies",
        "clinicalgov_get_study",
        "clinicalgov_get_api_info",
    }
    tool_messages = [
        message for message in completions.calls[1]["messages"] if message["role"] == "tool"
    ]
    assert "NCT01234567" in tool_messages[0]["content"]
