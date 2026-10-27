import os

import pytest

from app.ai import MetaAIClient
from app.config import get_settings
from app.schemas import StudySummary


@pytest.mark.skipif(os.getenv("RUN_META_INTEGRATION") != "1", reason="Live Meta integration is opt-in")
async def test_live_meta_structured_response() -> None:
    settings = get_settings()
    assert settings.meta_configured, "META_API_KEY and META_MODEL are required"
    result = await MetaAIClient(settings).generate_structured(
        schema=StudySummary,
        task="Extract this tiny synthetic protocol.",
        source="Synthetic protocol SYN-1 is a randomized Phase II study of 20 adults.",
    )
    assert result.protocol_number == "SYN-1"
