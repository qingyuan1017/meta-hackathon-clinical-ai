import os

import pytest

from cdisc_mcp.client import CDISCLibraryClient


@pytest.mark.skipif(os.getenv("RUN_CDISC_INTEGRATION") != "1", reason="Live CDISC integration is opt-in")
async def test_live_cdisc_products() -> None:
    result = await CDISCLibraryClient.from_settings().get("/mdr/products")
    assert isinstance(result, dict)
    assert result
