from __future__ import annotations

from mcp import Client
from pubmed_mcp.server import create_server


class FakePubMedClient:
    email = "owner@example.com"
    api_key = ""
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    max_results = 20

    async def search(self, query: str, **kwargs):
        if (kwargs["min_date"] is None) != (kwargs["max_date"] is None):
            raise ValueError("min_date and max_date must be supplied together")
        assert query == "asthma[Title]"
        assert kwargs == {
            "limit": 2,
            "offset": 0,
            "sort": "relevance",
            "date_type": None,
            "min_date": None,
            "max_date": None,
        }
        return {
            "query": query,
            "total_count": 1,
            "pmids": ["12345678"],
            "articles": [{"pmid": "12345678", "title": "Example"}],
        }

    async def fetch(self, pmids):
        return [{"pmid": value, "title": "Example"} for value in pmids]

    async def api_info(self):
        return {"einforesult": {"dbinfo": [{"dbname": "pubmed"}]}}


async def test_mcp_exposes_expected_read_only_tools() -> None:
    async with Client(create_server(FakePubMedClient())) as client:  # type: ignore[arg-type]
        result = await client.list_tools()

    assert {tool.name for tool in result.tools} == {
        "pubmed_status",
        "pubmed_search",
        "pubmed_get_articles",
    }


async def test_search_returns_structured_articles_and_source_notice() -> None:
    async with Client(create_server(FakePubMedClient())) as client:  # type: ignore[arg-type]
        result = await client.call_tool(
            "pubmed_search", {"query": "asthma[Title]", "limit": 2}
        )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["articles"][0]["pmid"] == "12345678"
    assert "not medical advice" in result.structured_content["source_notice"]


async def test_invalid_date_pair_is_a_model_visible_error() -> None:
    async with Client(create_server(FakePubMedClient())) as client:  # type: ignore[arg-type]
        result = await client.call_tool(
            "pubmed_search",
            {"query": "asthma", "min_date": "2025"},
        )

    assert result.is_error is True
    assert "must be supplied together" in result.content[0].text  # type: ignore[union-attr]
