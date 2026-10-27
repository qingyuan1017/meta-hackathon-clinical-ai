# Clinical AI Workbench MCP Adapter

This service exposes the workbench use-case registry, job submission/status, and schema-validated result revision through MCP. It delegates persistence, validation, AI generation, and deterministic rendering to the FastAPI service rather than reimplementing workflow logic.

## Local stdio

Start the FastAPI backend, then:

```powershell
cd workbench-mcp
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
clinical-workbench-mcp
```

The default API URL is `http://127.0.0.1:8000/api/v1`. Configure another address with `WORKBENCH_API_URL`.

## Streamable HTTP

Docker Compose exposes the adapter on `http://127.0.0.1:8002/mcp`. It has no inbound authentication and should remain on a trusted interface for this local hackathon application.

The MCP text submission tool intentionally does not accept local file paths or binary payloads. Use the web UI or multipart REST endpoint for PDF, DOCX, and XLSX inputs.
