import json
from types import SimpleNamespace

import pytest
from app.ai import MetaAIClient
from app.config import Settings


def test_decode_json_accepts_fenced_content() -> None:
    assert MetaAIClient._decode_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_decode_json_rejects_array() -> None:
    with pytest.raises(ValueError):
        MetaAIClient._decode_json("[1, 2]")


async def test_meta_client_executes_remote_clinicalgov_mcp_tool_call(monkeypatch) -> None:
    clinicalgov_tools = [
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
    openfda_tools = [
        SimpleNamespace(
            name=name,
            description=f"Description for {name}",
            input_schema={"type": "object", "properties": {}},
        )
        for name in (
            "list_openfda_endpoints",
            "describe_openfda_endpoint",
            "search_openfda",
            "lookup_openfda",
            "count_openfda",
        )
    ]
    pubmed_tools = [
        SimpleNamespace(
            name=name,
            description=f"Description for {name}",
            input_schema={"type": "object", "properties": {}},
        )
        for name in ("pubmed_search", "pubmed_get_articles")
    ]

    class FakeMCPClient:
        def __init__(self, url: str):
            assert url in {
                "http://clinicalgov.test/mcp",
                "http://openfda.test/mcp",
                "http://pubmed.test/mcp",
            }
            self.url = url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def list_tools(self):
            if self.url == "http://clinicalgov.test/mcp":
                tools = clinicalgov_tools
            elif self.url == "http://openfda.test/mcp":
                tools = openfda_tools
            else:
                tools = pubmed_tools
            return SimpleNamespace(tools=tools)

        async def call_tool(self, name: str, arguments: dict):
            assert self.url == "http://clinicalgov.test/mcp"
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
        openfda_mcp_enabled=True,
        openfda_mcp_url="http://openfda.test/mcp",
        pubmed_mcp_enabled=True,
        pubmed_mcp_url="http://pubmed.test/mcp",
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
        "list_openfda_endpoints",
        "describe_openfda_endpoint",
        "search_openfda",
        "lookup_openfda",
        "count_openfda",
        "pubmed_search",
        "pubmed_get_articles",
    }
    tool_messages = [
        message for message in completions.calls[1]["messages"] if message["role"] == "tool"
    ]
    assert "NCT01234567" in tool_messages[0]["content"]


async def test_meta_client_routes_openfda_tool_to_its_mcp_client() -> None:
    class FakeOpenFDAClient:
        async def call_tool(self, name: str, arguments: dict):
            assert name == "lookup_openfda"
            assert arguments == {
                "endpoint": "drug/ndc",
                "field": "brand_name.exact",
                "value": "Lipitor",
            }
            return SimpleNamespace(
                is_error=False,
                structured_content={"results": [{"brand_name": "Lipitor"}]},
                content=[],
            )

    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name="lookup_openfda",
            arguments=(
                '{"endpoint":"drug/ndc","field":"brand_name.exact",'
                '"value":"Lipitor"}'
            ),
        )
    )

    payload = await MetaAIClient._call_mcp_tool(
        {"lookup_openfda": FakeOpenFDAClient()},  # type: ignore[dict-item]
        tool_call,
    )

    assert json.loads(payload) == {
        "ok": True,
        "result": {"results": [{"brand_name": "Lipitor"}]},
    }


async def test_meta_client_routes_pubmed_tool_to_its_mcp_client() -> None:
    class FakePubMedClient:
        async def call_tool(self, name: str, arguments: dict):
            assert name == "pubmed_search"
            assert arguments == {"query": "asthma[Title]", "limit": 1}
            return SimpleNamespace(
                is_error=False,
                structured_content={
                    "articles": [{"pmid": "12345678", "title": "Example"}]
                },
                content=[],
            )

    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name="pubmed_search",
            arguments='{"query":"asthma[Title]","limit":1}',
        )
    )

    payload = await MetaAIClient._call_mcp_tool(
        {"pubmed_search": FakePubMedClient()},  # type: ignore[dict-item]
        tool_call,
    )

    assert json.loads(payload) == {
        "ok": True,
        "result": {"articles": [{"pmid": "12345678", "title": "Example"}]},
    }
