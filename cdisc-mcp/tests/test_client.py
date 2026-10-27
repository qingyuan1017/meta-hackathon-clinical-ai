import httpx
import pytest

from cdisc_mcp.client import CDISCConfigurationError, CDISCLibraryClient, CDISCLibraryError
from cdisc_mcp.config import Settings


async def test_client_sends_api_key_and_query_without_exposing_secret() -> None:
    secret = "test-subscription-key"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api-key"] == secret
        assert request.headers["accept"] == "application/json"
        assert request.url.path == "/api/mdr/search"
        assert request.url.params["q"] == "AGE"
        return httpx.Response(200, json={"items": [{"name": "AGE"}]})

    client = CDISCLibraryClient(secret, transport=httpx.MockTransport(handler))
    result = await client.get("/mdr/search", params={"q": "AGE"})

    assert result == {"items": [{"name": "AGE"}]}
    assert secret not in repr(result)


async def test_client_returns_safe_authentication_error() -> None:
    secret = "do-not-leak-this"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": f"Access denied for {secret}"})

    client = CDISCLibraryClient(secret, transport=httpx.MockTransport(handler))
    with pytest.raises(CDISCLibraryError) as exc_info:
        await client.get("/mdr/products")

    assert exc_info.value.status_code == 401
    assert secret not in str(exc_info.value)
    assert "API key" in str(exc_info.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/mdr/products",
        "/mdr/products?q=unsafe",
        "/mdr/../admin",
        "/unrelated/path",
    ],
)
def test_client_rejects_endpoints_outside_cdisc_read_surface(endpoint: str) -> None:
    with pytest.raises(ValueError):
        CDISCLibraryClient.validate_endpoint(endpoint)


def test_configuration_reads_cdisc_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDISC_LIBRARY_API_KEY", "from-environment")
    settings = Settings(_env_file=None)

    assert settings.cdisc_library_api_key == "from-environment"
    assert settings.cdisc_library_configured is True


def test_client_requires_api_key() -> None:
    with pytest.raises(CDISCConfigurationError, match="CDISC_LIBRARY_API_KEY"):
        CDISCLibraryClient("  ")
