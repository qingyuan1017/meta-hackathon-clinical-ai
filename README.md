# Clinical AI Artifact Workbench

A local, single-user hackathon application that uses Meta's OpenAI-compatible API to turn synthetic or de-identified clinical-study inputs into draft clinical artifacts.

> **Important:** This software is a demonstration. Outputs are not validated for regulatory submission, are not medical advice, and require review by qualified clinical, statistical, data-management, and programming professionals. Do not upload PHI or identifiable patient data.

## Included workflows

- Protocol extraction to structured JSON and Markdown
- Ten clinical document templates with DOCX and PDF output
- EDC build specifications and edit checks in JSON and XLSX
- SDTM mapping, R/SAS programs, annotated CRF, and draft Define-XML 2.1
- TLF shells with DOCX and R/SAS program scaffolds

## Use-case architecture

Each workflow is a first-class use case with one shared contract:

- `backend/app/use_cases/` owns its input rules, model schema, generation logic, deterministic renderer, output formats, and MCP dependencies.
- `skills/` contains the model-facing operating skill for the use case.
- FastAPI exposes the same registry through `GET /api/v1/use-cases` and `GET /api/v1/use-cases/{id}`.
- The Workbench MCP adapter on port 8002 delegates to those APIs; it does not duplicate prompts or persistence logic.
- Users can edit a completed structured result in the web UI or with `PUT /api/v1/jobs/{id}/result`. The backend validates the use-case schema and rebuilds all artifacts without another model call.

This keeps agent-driven skill runs and direct user/API work on the same schemas and rendering path.

## Quick start

1. Copy `.env.example` to `.env` and set `META_API_KEY` and `META_MODEL`.
2. Start the application:

   ```powershell
   docker compose up --build
   ```

3. Open http://localhost:3000. The API and interactive OpenAPI documentation are available at http://localhost:8000/docs. MCP endpoints are available at `http://localhost:8001/mcp` for CDISC Library and `http://localhost:8002/mcp` for the workbench. Synthetic inputs, including a generated blank CRF PDF, are downloadable from the dashboard. If port 3000 is already occupied, set another free port such as `WEB_PORT=3300` before starting Compose.

Generated files and SQLite history are kept in the `clinical-ai-data` Docker volume until a job is deleted.

## Local development

### Backend

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The backend requires Python 3.12 or newer. On Windows, use the versioned `py -3.12`
command above instead of an unversioned `python`, which may point to an older installation.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

The frontend defaults to `http://localhost:8000`; override it with `NEXT_PUBLIC_API_URL`.

## Meta configuration

| Variable | Purpose |
| --- | --- |
| `META_API_KEY` | Server-side Meta API credential |
| `META_API_BASE_URL` | OpenAI-compatible endpoint; defaults to `https://api.llama.com/compat/v1/` |
| `META_MODEL` | Exact model ID enabled for the account |
| `FRONTEND_ORIGIN` | Allowed browser origin |
| `MAX_FILE_MB` / `MAX_PDF_PAGES` | Upload safety limits |

The application never exposes the key to the browser. Generation remains disabled until both a key and model are configured. There is deliberately no runtime canned-result fallback.

## CDISC Library MCP server

`cdisc-mcp` is a standalone service with its own Python package, dependencies, tests, container, and runtime configuration. It does not import or run inside the clinical FastAPI backend. The service exposes focused read-only tools for products, search, SDTM/SDTMIG/SENDIG datasets and variables, ADaM products, controlled terminology, Biomedical Concepts, and SDTM Dataset Specializations. A guarded generic read tool supports other current and future `/mdr` and `/cosmos` GET endpoints.

1. Obtain a subscription key from the [CDISC Library API Management Developer Portal](https://api.developer.library.cdisc.org/).
2. Put the key in the root `.env` file or in the MCP host process environment:

   ```dotenv
   CDISC_LIBRARY_API_KEY=your-subscription-key
   ```

3. Install the standalone service and run its stdio transport from the repository root:

   ```powershell
   cd cdisc-mcp
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   cd ..
   cdisc-mcp\.venv\Scripts\cdisc-library-mcp.exe
   ```

The last command intentionally waits without printing because stdio is the MCP protocol channel. Configure your MCP host to launch that executable with the repository root as its working directory. If the host does not inherit custom environment variables, set `CDISC_LIBRARY_API_KEY` in that host's per-server environment configuration instead. Do not put the key in frontend variables or commit it to source control.

For a separately running network service, start only its container:

```powershell
docker compose up --build cdisc-mcp
```

MCP clients connect with Streamable HTTP at `http://localhost:8001/mcp`. Compose binds port 8001 to `127.0.0.1` only; add authentication and transport-security allowlists before exposing the service outside the local machine. You can also run HTTP without Docker:

```powershell
cdisc-mcp\.venv\Scripts\cdisc-library-mcp.exe --transport streamable-http --port 8001
```

| Variable | Purpose |
| --- | --- |
| `CDISC_LIBRARY_API_KEY` | CDISC Library subscription key; required for Library data requests |
| `CDISC_LIBRARY_BASE_URL` | REST base URL; defaults to `https://library.cdisc.org/api` |
| `CDISC_LIBRARY_TIMEOUT_SECONDS` | Outbound Library request timeout; defaults to 30 seconds |
| `CDISC_LIBRARY_COSMOS_VERSION` | COSMoS API version; defaults to `v2` |
| `CDISC_MCP_TRANSPORT` | `stdio` locally or `streamable-http` for a network service |
| `CDISC_MCP_HOST` / `CDISC_MCP_PORT` | HTTP bind address and port; local defaults are `127.0.0.1:8001` |

The server returns authoritative Library JSON without silently translating field names into this application's Pydantic schemas. Call `cdisc_list_products` first and use the version/product identifiers and `href` values it returns; CDISC endpoint identifiers are not always the same as display labels such as “SDTMIG 3.4”. `cdisc_library_status` reports only whether a key is configured and never returns the key itself.

## Workbench MCP server and direct editing API

The standalone `workbench-mcp` package presents the five registered use cases to MCP clients. Its tools discover contracts, submit synthetic/de-identified text jobs, poll history, and apply complete structured-result revisions. PDF, DOCX, and XLSX submissions remain on the web UI or multipart API so the MCP service never receives host file paths.

The corresponding REST interfaces are:

- `GET /api/v1/use-cases` and `GET /api/v1/use-cases/{id}` for metadata and JSON Schema
- `POST /api/v1/jobs/{use-case}` for generation
- `GET /api/v1/jobs/{id}` for status and results
- `PUT /api/v1/jobs/{id}/result` for human revision and deterministic artifact rebuilding

Repository-local skills under `skills/` describe how an agent coordinates these Workbench MCP tools with the read-only CDISC Library MCP tools where standards metadata is needed.

## Tests

```powershell
cd backend
pytest

cd ..\frontend
npm test
npm run build

cd ..\cdisc-mcp
pytest
```

Set `RUN_META_INTEGRATION=1` to opt into the live API smoke test. Normal automated tests use an injected test double that is not available in the running application.

Set `RUN_CDISC_INTEGRATION=1` to opt into a live `/mdr/products` smoke test. It also requires `CDISC_LIBRARY_API_KEY`. Normal tests use a mock HTTP transport and do not call CDISC Library.

The standalone `samples/generate_blank_crf.py` helper can also create `samples/blank-crf.pdf` for use outside the running application.

## Standards posture

SDTM outputs are labeled for SDTMIG 3.4 and Define-XML 2.1, but this repository does not distribute CDISC standards content and does not claim conformance. XML is checked for well-formedness and internal references only. All generated programs contain review markers and are never executed by the application.
