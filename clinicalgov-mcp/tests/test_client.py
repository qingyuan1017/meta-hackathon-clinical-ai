import httpx
import pytest

from clinicalgov_mcp.client import ClinicalTrialsGovClient, ClinicalTrialsGovError


async def test_client_searches_with_query_and_no_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/json"
        assert "authorization" not in request.headers
        assert request.url.path == "/api/v2/studies"
        assert request.url.params["query.cond"] == "glioblastoma"
        assert request.url.params["pageSize"] == "5"
        return httpx.Response(200, json={"studies": [{"protocolSection": {}}], "totalCount": 1})

    client = ClinicalTrialsGovClient(transport=httpx.MockTransport(handler))
    result = await client.get("/studies", params={"query.cond": "glioblastoma", "pageSize": 5})

    assert result["totalCount"] == 1


async def test_client_returns_safe_not_found_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Study not found"})

    client = ClinicalTrialsGovClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ClinicalTrialsGovError) as exc_info:
        await client.get("/studies/NCT00000000")

    assert exc_info.value.status_code == 404
    assert "not found" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/studies",
        "/studies?query.cond=unsafe",
        "/studies/../version",
        "/studies/not-an-nct-id",
        "/unrelated/path",
    ],
)
def test_client_rejects_endpoints_outside_read_surface(endpoint: str) -> None:
    with pytest.raises(ValueError):
        ClinicalTrialsGovClient.validate_endpoint(endpoint)


def test_client_normalizes_nct_id() -> None:
    assert ClinicalTrialsGovClient.normalize_nct_id(" nct01234567 ") == "NCT01234567"


def test_client_rejects_invalid_nct_id() -> None:
    with pytest.raises(ValueError, match="eight digits"):
        ClinicalTrialsGovClient.normalize_nct_id("NCT123")
