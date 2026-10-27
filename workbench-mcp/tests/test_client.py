import httpx
import pytest

from workbench_mcp.client import WorkbenchClient


@pytest.mark.asyncio
async def test_client_reads_use_cases() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/use-cases"
        return httpx.Response(200, json=[{"id": "sdtm"}])

    client = WorkbenchClient(
        base_url="https://workbench.test/api/v1",
        transport=httpx.MockTransport(handler),
    )
    assert await client.request("GET", "/use-cases") == [{"id": "sdtm"}]


@pytest.mark.asyncio
async def test_client_surfaces_api_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "invalid result"})

    client = WorkbenchClient(base_url="https://workbench.test/api/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="invalid result"):
        await client.request("PUT", "/jobs/job-1/result", json={"result": {}})
