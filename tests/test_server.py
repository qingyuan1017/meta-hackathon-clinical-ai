from __future__ import annotations

import httpx
import pytest
from mcp import Client

from openfda_mcp.client import OpenFDAClient
from openfda_mcp.config import Settings
from openfda_mcp.server import create_server


@pytest.mark.asyncio
async def test_server_advertises_expected_tools() -> None:
    server = create_server(OpenFDAClient(Settings(max_retries=0)))
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools.tools} == {
        "list_openfda_endpoints",
        "describe_openfda_endpoint",
        "search_openfda",
        "lookup_openfda",
        "count_openfda",
    }


@pytest.mark.asyncio
async def test_search_tool_returns_structured_projected_data_and_notice() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "meta": {"results": {"skip": 0, "limit": 1, "total": 1}},
                "results": [{"product_ndc": "0001-0001", "brand_name": "Example", "extra": 1}],
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.fda.gov", transport=httpx.MockTransport(handler)
    ) as http_client:
        openfda = OpenFDAClient(
            Settings(timeout_seconds=5.0, max_results=20, max_retries=0),
            http_client=http_client,
        )
        async with Client(create_server(openfda)) as client:
            result = await client.call_tool(
                "search_openfda",
                {"endpoint": "drug/ndc", "limit": 1, "fields": ["product_ndc"]},
            )

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["results"] == [{"product_ndc": "0001-0001"}]
    assert "not medical advice" in result.structured_content["clinical_safety_notice"]


@pytest.mark.asyncio
async def test_invalid_endpoint_is_a_model_visible_tool_error() -> None:
    server = create_server(OpenFDAClient(Settings(max_retries=0)))
    async with Client(server) as client:
        result = await client.call_tool(
            "search_openfda", {"endpoint": "private/internal", "limit": 1}
        )
    assert result.is_error
    assert "Unsupported endpoint" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_configured_result_cap_is_enforced() -> None:
    server = create_server(OpenFDAClient(Settings(max_results=5, max_retries=0)))
    async with Client(server) as client:
        result = await client.call_tool(
            "search_openfda", {"endpoint": "drug/ndc", "limit": 6}
        )
    assert result.is_error
    assert "between 1 and 5" in result.content[0].text  # type: ignore[union-attr]

