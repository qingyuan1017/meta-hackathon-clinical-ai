import os

import pytest

from clinicalgov_mcp.client import ClinicalTrialsGovClient


@pytest.mark.skipif(
    os.getenv("RUN_CLINICALGOV_INTEGRATION") != "1",
    reason="Live ClinicalTrials.gov integration is opt-in",
)
async def test_live_clinicalgov_version_and_known_study() -> None:
    client = ClinicalTrialsGovClient.from_settings()
    version = await client.get("/version")
    study = await client.get("/studies/NCT03619213", params={"fields": "NCTId,BriefTitle"})

    assert isinstance(version, dict)
    assert study["protocolSection"]["identificationModule"]["nctId"] == "NCT03619213"
