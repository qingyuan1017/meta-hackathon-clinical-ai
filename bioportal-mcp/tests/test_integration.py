import os

import pytest

from bioportal_mcp.client import BioPortalClient


@pytest.mark.skipif(
    os.getenv("RUN_BIOPORTAL_INTEGRATION") != "1",
    reason="Live BioPortal integration is opt-in",
)
async def test_live_bioportal_ncit_metadata() -> None:
    result = await BioPortalClient.from_settings().get(
        "/ontologies/NCIT",
        params={"include": "acronym,name", "display_context": False},
    )
    assert isinstance(result, dict)
    assert result["acronym"] == "NCIT"
