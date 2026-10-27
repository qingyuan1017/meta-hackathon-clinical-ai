import os

import pytest
from pubmed_mcp.client import PubMedClient


@pytest.mark.skipif(
    os.getenv("RUN_PUBMED_INTEGRATION") != "1",
    reason="Live PubMed integration is opt-in",
)
async def test_live_pubmed_search() -> None:
    client = PubMedClient.from_settings()
    result = await client.search("asthma[Title]", limit=1)

    assert result["total_count"] > 0
    assert len(result["articles"]) == 1
    assert result["articles"][0]["pmid"]
