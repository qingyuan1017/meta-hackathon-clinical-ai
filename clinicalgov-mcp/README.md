# ClinicalTrials.gov MCP Service

Standalone, read-only Model Context Protocol service for the public ClinicalTrials.gov API v2. It is packaged and deployed independently from the clinical workbench backend.

## Run locally over stdio

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
clinicalgov-mcp
```

## Run as a Streamable HTTP service

```powershell
clinicalgov-mcp --transport streamable-http --host 127.0.0.1 --port 8003
```

Connect an MCP client to `http://127.0.0.1:8003/mcp`. From the repository root, Docker Compose runs the same service with:

```powershell
docker compose up --build clinicalgov-mcp
```

The service has no inbound authentication. Keep it bound to a trusted interface or place authentication in front of it before remote deployment.

## Test

```powershell
pytest
```

Set `RUN_CLINICALGOV_INTEGRATION=1` to include the live API version and known-study test. The normal suite uses mocked HTTP and does not call ClinicalTrials.gov.
