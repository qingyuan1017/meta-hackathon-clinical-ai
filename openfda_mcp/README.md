# openFDA MCP service

A standalone, read-only MCP service for public [openFDA](https://open.fda.gov/apis/)
datasets. The service is used by the repository's Meta model integration and can
also be called by any Streamable HTTP MCP client.

The data is for research and informational use. It is not medical advice, and
adverse-event reports do not establish causality, incidence, or comparative risk.

## Tools

- `list_openfda_endpoints`
- `describe_openfda_endpoint`
- `search_openfda`
- `lookup_openfda`
- `count_openfda`

The service allowlists 19 drug, device, food, cosmetic, tobacco, and veterinary
datasets. Network results contain upstream metadata, key-free provenance URLs, and
a clinical-use notice. Query limits, endpoint validation, retries, and optional
field projection keep model context bounded.

## Docker

From the repository root:

```powershell
docker compose up --build -d openfda-mcp
```

- Other Compose services connect to `http://openfda-mcp:8000/mcp`.
- Host MCP clients connect to `http://127.0.0.1:8765/mcp`.
- The liveness endpoint is `/health`.

The image runs as UID 10001. Compose binds the port to localhost and supplies exact
Host-header allowlist values for DNS-rebinding protection.

## Local development

Python 3.11 or newer and `uv` are required:

```powershell
cd openfda_mcp
uv sync --dev
uv run pytest
uv run ruff check .
uv run openfda-mcp
```

The command defaults to stdio. To run Streamable HTTP directly:

```powershell
uv run openfda-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENFDA_API_KEY` | unset | Free openFDA key; recommended for regular use |
| `OPENFDA_TIMEOUT_SECONDS` | `30` | Upstream request timeout |
| `OPENFDA_MAX_RESULTS` | `100` | Maximum records returned by one tool call |
| `OPENFDA_MAX_RETRIES` | `2` | Retries for rate limits and transient failures |
| `OPENFDA_MCP_ALLOWED_HOSTS` | local and Compose hosts | Exact HTTP Host allowlist |
| `OPENFDA_MCP_ALLOWED_ORIGINS` | unset | Exact browser Origin allowlist |

Request an API key and review rate limits in the
[openFDA authentication documentation](https://open.fda.gov/apis/authentication/).
