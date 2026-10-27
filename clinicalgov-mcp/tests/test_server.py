from mcp import Client

from clinicalgov_mcp.server import mcp


async def test_mcp_exposes_expected_read_only_tools() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == {
        "clinicalgov_status",
        "clinicalgov_search_studies",
        "clinicalgov_get_study",
        "clinicalgov_get_api_info",
        "clinicalgov_read_endpoint",
    }


async def test_mcp_search_builds_bounded_official_api_query(monkeypatch) -> None:
    requests: list[tuple[str, dict]] = []

    class FakeClient:
        async def get(self, endpoint: str, *, params: dict | None = None):
            requests.append((endpoint, params or {}))
            return {"studies": [], "totalCount": 0}

    monkeypatch.setattr("clinicalgov_mcp.server._client", lambda: FakeClient())
    async with Client(mcp) as client:
        result = await client.call_tool(
            "clinicalgov_search_studies",
            {
                "condition": "multiple sclerosis",
                "overall_status": ["RECRUITING"],
                "page_size": 5,
            },
        )

    assert result.is_error is False
    assert requests[0][0] == "/studies"
    assert requests[0][1]["query.cond"] == "multiple sclerosis"
    assert requests[0][1]["filter.overallStatus"] == "RECRUITING"
    assert requests[0][1]["pageSize"] == 5
