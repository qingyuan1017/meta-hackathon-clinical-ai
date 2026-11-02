# Muse Code integration

Muse Code can use the Clinical AI Workbench through the repository's project-level
MCP configuration and clinical skills.

## Prerequisites

- Muse Code 1.3 or later is installed and authenticated.
- Docker Desktop is running.
- The repository services are running:

  ```powershell
  docker compose up --build -d api workbench-mcp cdisc-mcp
  ```

## Start Muse Code

From the repository root, run:

```powershell
muse
```

Choose **Trust and continue** when Muse Code asks whether to trust the workspace.
Trust is required before Muse Code loads the checked-in `.mcp.json` file and the
skills under `.codex/skills`.

In Muse Code, run `/mcp` and confirm that these servers are available:

- `clinical-ai-workbench` at `http://127.0.0.1:8002/mcp`
- `cdisc-library` at `http://127.0.0.1:8001/mcp`

Run `muse skills list --trust-workspace` in a terminal to confirm that the five
`clinical-*` project skills were discovered. Muse Code scans repository-local
`.codex/skills`, so the existing skill definitions are shared without copying
them into a Muse-specific directory.

## Example

After the services are available, invoke a clinical skill from Muse Code:

```text
/clinical-sdtm-artifacts Submit an SDTM job using metadata at C:\study\edc.xlsx, raw datasets at C:\study\dm.csv and C:\study\ae.csv, and the blank CRF at C:\study\blank-crf.pdf. I confirm that every file is synthetic or de-identified and contains no PHI.
```

Muse Code runs `scripts/submit_sdtm.py` on the client machine. The helper opens
the selected files and uploads their bytes as multipart data to the Workbench
REST API; the server never receives or resolves the client filesystem paths.
Muse then follows the created job through the MCP tools. The explicit
synthetic/de-identified acknowledgement is required. The helper accepts:

- `--metadata` with one or more required JSON/XLSX files
- `--raw` with optional CSV/XPT datasets
- `--crf` with one optional searchable blank CRF PDF
- `--validation-report` with one optional Pinnacle 21 CSV/XLSX report

For direct use outside an interactive Muse Code session:

```powershell
python scripts/submit_sdtm.py --metadata "C:\study\edc.xlsx" --raw "C:\study\dm.csv" "C:\study\ae.csv" --crf "C:\study\blank-crf.pdf" --acknowledge-deidentified
```

## Hosted Workbench

For a Workbench deployed on the web, point the client-side uploader at the
remote API:

```powershell
$env:WORKBENCH_API_TOKEN = "token-issued-by-your-deployment"
python scripts/submit_sdtm.py --api-url "https://workbench.example.com/api/v1" --metadata "C:\study\edc.xlsx" --acknowledge-deidentified
```

`WORKBENCH_API_TOKEN` is optional and is forwarded as a bearer token for a
reverse proxy or future authenticated deployment. Do not put tokens in Muse
prompts or checked-in configuration.

The MCP control connection must likewise target the hosted MCP endpoint rather
than the localhost defaults in `.mcp.json`. Configure the deployment-specific
URL in the Muse settings used for that environment and protect it with OAuth or
another trusted authentication layer. The current local hackathon MCP services
have no inbound authentication and must not be exposed directly to the web.

Docker Compose now persists validated source uploads in MinIO under
`jobs/<job-id>/inputs/<safe-filename>`. The API still keeps a local job workspace
for parsers, deterministic renderers, and the isolated SDTM runner; missing
workspace inputs can be restored from MinIO with checksum verification. The
local MinIO API and console bind to `127.0.0.1:9000` and `127.0.0.1:9001` by
default. Change the development credentials before any hosted deployment.

If Muse Code runs remotely and cannot access files on the user's computer, it
cannot use a local path at all. In that case, upload the files through the
Workbench browser UI or another client-side attachment flow.

Both MCP servers are optional at Muse Code startup, so ordinary repository work
can continue while the Docker stack is stopped. A clinical workflow still needs
the Workbench server, and standards-aware workflows also need the CDISC Library
server. Both endpoints bind to localhost and have no inbound authentication; do
not expose them on an untrusted network.

Binary PDF, DOCX, and XLSX submissions still use the Workbench web UI or REST
upload endpoints. The MCP submission tool intentionally accepts text only.
