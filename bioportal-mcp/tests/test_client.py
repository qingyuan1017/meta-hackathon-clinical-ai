import httpx
import pytest

from bioportal_mcp.client import (
    BioPortalClient,
    BioPortalConfigurationError,
    BioPortalError,
)
from bioportal_mcp.config import Settings


async def test_client_uses_documented_authorization_header_and_query() -> None:
    secret = "test-bioportal-key"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"apikey token={secret}"
        assert request.headers["accept"] == "application/json"
        assert request.url.path == "/search"
        assert request.url.params["q"] == "melanoma"
        return httpx.Response(200, json={"collection": [{"prefLabel": "Melanoma"}]})

    client = BioPortalClient(secret, transport=httpx.MockTransport(handler))
    result = await client.get("/search", params={"q": "melanoma"})

    assert result == {"collection": [{"prefLabel": "Melanoma"}]}
    assert secret not in repr(result)


async def test_client_preserves_percent_encoded_class_iri_path() -> None:
    encoded = "http%3A%2F%2Fpurl.bioontology.org%2Fontology%2FSNOMEDCT%2F410607006"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.decode().split("?")[0].endswith(encoded)
        return httpx.Response(200, json={"prefLabel": "Organism"})

    client = BioPortalClient("key", transport=httpx.MockTransport(handler))
    result = await client.get(f"/ontologies/SNOMEDCT/classes/{encoded}")

    assert result == {"prefLabel": "Organism"}


async def test_client_returns_safe_authentication_error() -> None:
    secret = "do-not-leak-this"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": f"Access denied for {secret}"})

    client = BioPortalClient(secret, transport=httpx.MockTransport(handler))
    with pytest.raises(BioPortalError) as exc_info:
        await client.get("/ontologies/NCIT")

    assert exc_info.value.status_code == 401
    assert secret not in str(exc_info.value)
    assert "API key" in str(exc_info.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/search",
        "/search?q=unsafe",
        "/ontologies/../users",
        "/users",
        "/mappings",
    ],
)
def test_client_rejects_endpoints_outside_focused_read_surface(endpoint: str) -> None:
    with pytest.raises(ValueError):
        BioPortalClient.validate_endpoint(endpoint)


def test_configuration_reads_bioportal_key_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIOPORTAL_API_KEY", "from-environment")
    settings = Settings(_env_file=None)

    assert settings.bioportal_api_key == "from-environment"
    assert settings.bioportal_configured is True


def test_client_requires_api_key() -> None:
    with pytest.raises(BioPortalConfigurationError, match="BIOPORTAL_API_KEY"):
        BioPortalClient("  ")
