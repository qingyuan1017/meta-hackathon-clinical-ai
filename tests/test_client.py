from __future__ import annotations

import httpx
import pytest

from openfda_mcp.client import OpenFDAClient, OpenFDAError, exact_search, project_records
from openfda_mcp.config import Settings


def settings(**overrides: object) -> Settings:
    values = {
        "api_key": "secret-key",
        "timeout_seconds": 5.0,
        "max_results": 100,
        "max_retries": 0,
        "user_agent": "test-client",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_query_builds_request_and_redacts_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "api_key" not in request.url.params
        assert request.headers["Authorization"].startswith("Basic ")
        assert "secret-key" not in str(request.url)
        assert request.url.params["search"] == 'brand_name.exact:"LIPITOR"'
        assert request.url.params["limit"] == "2"
        return httpx.Response(
            200,
            json={"meta": {"results": {"total": 1}}, "results": [{"brand_name": "Lipitor"}]},
        )

    async with httpx.AsyncClient(
        base_url="https://api.fda.gov", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = OpenFDAClient(settings(), http_client=http_client)
        result = await client.query(
            "drug/ndc", search='brand_name.exact:"LIPITOR"', limit=2
        )

    assert "api_key" not in result["source"]["url"]
    assert result["source"]["dataset"] == "drug/ndc"
    assert result["results"][0]["brand_name"] == "Lipitor"


@pytest.mark.asyncio
async def test_openfda_404_becomes_clear_no_matches_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "No matches found!"}},
        )

    async with httpx.AsyncClient(
        base_url="https://api.fda.gov", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = OpenFDAClient(settings(), http_client=http_client)
        with pytest.raises(OpenFDAError, match="No openFDA records matched"):
            await client.query("drug/event", search="safetyreportid:nope")


@pytest.mark.asyncio
async def test_transient_status_is_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"meta": {}, "results": [{"ok": True}]})

    async with httpx.AsyncClient(
        base_url="https://api.fda.gov", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = OpenFDAClient(settings(max_retries=1), http_client=http_client)
        result = await client.query("drug/ndc", limit=1)

    assert calls == 2
    assert result["results"] == [{"ok": True}]


def test_rejects_unknown_endpoint_and_normalizes_known_endpoint() -> None:
    client = OpenFDAClient(settings())
    with pytest.raises(OpenFDAError, match="Unsupported endpoint"):
        client.normalize_endpoint("https://example.com/private")
    assert client.normalize_endpoint("/DRUG/EVENT.json") == "drug/event"


def test_exact_search_escapes_quotes_and_backslashes() -> None:
    assert exact_search("openfda.brand_name.exact", 'A "quoted" \\ name') == (
        'openfda.brand_name.exact:"A \\"quoted\\" \\\\ name"'
    )


def test_project_records_supports_paths_through_arrays() -> None:
    payload = {
        "meta": {"results": {"total": 1}},
        "results": [
            {
                "safetyreportid": "123",
                "patient": {
                    "reaction": [
                        {"reactionmeddrapt": "HEADACHE"},
                        {"reactionmeddrapt": "NAUSEA"},
                    ]
                },
                "unused": "large value",
            }
        ],
    }
    result = project_records(
        payload, ["safetyreportid", "patient.reaction.reactionmeddrapt"]
    )
    assert result["results"] == [
        {
            "safetyreportid": "123",
            "patient.reaction.reactionmeddrapt": ["HEADACHE", "NAUSEA"],
        }
    ]

