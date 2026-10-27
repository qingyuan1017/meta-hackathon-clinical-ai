# CDISC Library MCP Service

Standalone, read-only Model Context Protocol service for the CDISC Library API. It is packaged and deployed independently from the clinical workbench backend.

## Configuration

Set `CDISC_LIBRARY_API_KEY` in the process environment or in the working directory's `.env` file. Optional settings are documented in `.env.example`.

## Run locally over stdio

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
cdisc-library-mcp
```

Configure a local MCP host to launch the `cdisc-library-mcp` executable. Standard output is reserved for the MCP protocol.

## Run as a Streamable HTTP service

```powershell
cdisc-library-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

Connect an MCP client to `http://127.0.0.1:8001/mcp`. The service has no inbound authentication, so keep it on a trusted interface or place authentication in front of it before remote deployment.

From the repository root, Docker Compose runs the same service on `http://localhost:8001/mcp`:

```powershell
docker compose up --build cdisc-mcp
```

## Test

```powershell
pytest
```

Set `RUN_CDISC_INTEGRATION=1` to include the live product-catalog test. The normal suite uses mocked HTTP and does not call CDISC Library.
