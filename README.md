# Clinical AI Artifact Workbench

A local, single-user hackathon application that uses Meta's OpenAI-compatible API to turn synthetic or de-identified clinical-study inputs into draft clinical artifacts.

> **Important:** This software is a demonstration. Outputs are not validated for regulatory submission, are not medical advice, and require review by qualified clinical, statistical, data-management, and programming professionals. Do not upload PHI or identifiable patient data.

## Included workflows

- Protocol extraction to structured JSON, Markdown, and CDISC USDM 4.0 JSON accepted only after the complete CORE conformance gate passes
- Ten clinical document templates with DOCX and PDF output
- EDC build specifications and edit checks in JSON and XLSX
- SDTM mapping, R/SAS programs, annotated CRF, and draft Define-XML 2.1
- TLF shells with DOCX and R/SAS program scaffolds

## Use-case architecture

Each workflow is a first-class use case with one shared contract. The agent and use-case layers have different responsibilities:

- `backend/app/agents/<agent>/` owns that specialist's identity, model instructions, and tool selection. Shared agent infrastructure is limited to the registry, tool catalog, and bounded execution loop.
- `backend/app/use_cases/` is the model-independent application layer: it owns input rules, result schemas, source preparation, deterministic rendering, output formats, and MCP dependencies.
- `.codex/skills/` contains the Codex-facing operating skill for each use case.
- FastAPI exposes the same registry through `GET /api/v1/use-cases` and `GET /api/v1/use-cases/{id}`.
- The Workbench MCP adapter on port 8002 delegates to those APIs; it does not duplicate prompts or persistence logic.
- Users can edit a completed structured result in the web UI or with `PUT /api/v1/jobs/{id}/result`. The backend validates the use-case schema and rebuilds all artifacts without another model call.

```text
backend/app/
├── agents/
│   ├── protocol_extraction/  # agent.py + instructions.md
│   ├── clinical_document/    # agent.py + instructions.md
│   ├── edc_design/           # agent.py + instructions.md
│   ├── sdtm/                 # agent.py + instructions.md
│   ├── tlf/                  # agent.py + instructions.md
│   ├── registry.py
│   ├── runtime.py
│   └── tool_catalog.py
└── use_cases/                # schemas, inputs, rendering, artifact contracts
```

Every `POST /api/v1/jobs/{workflow}` call runs the workflow's specialist-agent convention. Protocol extraction first runs three parallel sub-agents for design/endpoints, conduct/eligibility, and safety/ambiguities; its lead agent then rereads the original source and reconciles their drafts into the only accepted result. The Codex skill and all four backend protocol agents use `backend/app/agents/protocol_extraction/extraction_policy.md` as their shared clinical extraction policy. SDTM follows the same lead/specialist convention with three ordered mapping agents and the shared policy in `backend/app/agents/sdtm/mapping_policy.md`. Other workflows use one specialist loop. Every agent must inspect the live contract, read every available source chunk, use at most one tool per turn, and submit a schema-valid result before deterministic rendering begins. Lead progress is saved under `data/jobs/<job-id>/agent/progress.json`; traces contain no API credential and are removed when the job is deleted.

Protocol rendering maps the reviewed summary into the official CDISC USDM 4.0 API model and first validates it with CDISC's pinned `usdm` reference package. It then runs the full 207-rule USDM 4.0 set bundled with the official CDISC CORE 0.17.1 release. The gate fails closed for findings, execution errors, unknown statuses, incomplete reports, runtime failures, and technical skips; only raw skips explicitly reported as `Outside scope` are accepted as non-applicable. A successful bundle contains `usdm.json`, the unmodified official `core-report.json`, and the Workbench policy result `core-conformance.json`. A failed job retains those diagnostics for review but never labels the USDM conformant.

The API image fetches the official CORE v0.17.1 source at pinned release commit `2a90a3872a7e3b07c15abe84744026c94a7a04b0`, including its release cache, and installs `cdisc-rules-engine==0.17.1`. Local non-container runs must set `CORE_CLI_PATH` to the matching checked-out `core.py`. Changing the engine or cache requires an explicit ruleset-count and policy review; silently updating the cache would make conformance results non-reproducible.

The SDTM use case has three sequential human review gates. EDC JSON/XLSX is required; a blank CRF PDF is optional for code-only generation and is needed only when an annotated CRF should be produced. A source-normalization agent converts deterministically extracted JSON/XLSX content into a typed `EDCSourceSpecification` with dataset, variable, key, codelist, form/question, and file/sheet/row provenance metadata, then pauses for approval. The domain specialist maps every approved raw or existing-SDTM source to target domains and pauses again. The variable specialist adds traceability, value-level metadata, and aCRF labels when a CRF exists, then pauses for a third approval. Only after all three reviewed plans are accepted does rule augmentation contribute domain preparation plus R/SAS expressions. The registered SDTM lead reconciles the approved mappings and rule draft under the shared mapping policy and submits the complete plan used for deterministic rendering.

Completed SDTM jobs open a five-tab review workspace instead of a raw JSON-only form: Domain mapping, Variable & VLM, Rule augmentation, aCRF review, and Define-XML. Reviewers can drag raw or existing-SDTM datasets onto target domains, import versioned domain metadata through the configured CDISC Library MCP service, modify standard variables or add sponsor SUPP/VLM qualifiers in a matrix, review R/SAS rule expressions, and inspect the derived XML before or after schema-validated artifact rebuilding. The aCRF tab displays the annotated PDF when a blank CRF was supplied and otherwise explains that the code-only job intentionally omitted it.

This separation is intentional: an agent is a probabilistic planner that calls tools and drafts structured content, while a use case is the deterministic contract that validates, persists, edits, and renders that content. It keeps agent-driven runs and direct user/API edits on the same schemas and artifact path; removing `use_cases` would either couple rendering to the model loop or duplicate that logic in the API.

## Quick start

1. Copy `.env.example` to `.env`, set `META_API_KEY` and `META_MODEL`, and set a real `PUBMED_EMAIL` contact address (or disable PubMed with `PUBMED_MCP_ENABLED=false`).
2. Start the application:

   ```powershell
   docker compose up --build
   ```

3. Open http://localhost:3000. The API and interactive OpenAPI documentation are available at http://localhost:8000/docs. MCP endpoints are available at `http://localhost:8001/mcp` for CDISC Library, `http://localhost:8002/mcp` for the workbench, `http://localhost:8003/mcp` for ClinicalTrials.gov, `http://localhost:8004/mcp` for NCBO BioPortal, `http://localhost:8005/mcp` for PubMed, and `http://localhost:8765/mcp` for openFDA. Synthetic inputs, including a generated blank CRF PDF, are downloadable from the dashboard. If port 3000 is already occupied, set another free port such as `WEB_PORT=3300` before starting Compose.

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
| `META_API_BASE_URL` | OpenAI-compatible Meta Model API endpoint; defaults to `https://api.meta.ai/v1` |
| `META_MODEL` | Exact model ID enabled for the account |
| `AGENT_MAX_TURNS` | Maximum turns for one specialist-agent run; defaults to 20 |
| `AGENT_MAX_REMOTE_TOOL_CALLS` | Maximum optional MCP calls per agent run; defaults to 6 |
| `CDISC_MCP_ENABLED` | Allow the EDC, SDTM, and TLF agents to use CDISC Library tools |
| `CDISC_MCP_URL` | Backend connection URL; defaults to `http://127.0.0.1:8001/mcp` |
| `CLINICALGOV_MCP_ENABLED` | Allow Meta generation to use the separate ClinicalTrials.gov MCP service |
| `CLINICALGOV_MCP_URL` | Backend connection URL; defaults to `http://127.0.0.1:8003/mcp` |
| `CLINICALGOV_MAX_TOOL_ROUNDS` | Maximum registry tool-call rounds per model completion; defaults to 3 |
| `OPENFDA_MCP_ENABLED` | Allow Meta generation to query the read-only openFDA MCP service |
| `OPENFDA_MCP_URL` | Backend connection URL; defaults to `http://127.0.0.1:8765/mcp` |
| `OPENFDA_MAX_TOOL_ROUNDS` | Maximum openFDA tool-call rounds per model completion; defaults to 3 |
| `BIOPORTAL_MCP_ENABLED` | Allow Meta generation to query the read-only NCBO BioPortal MCP service |
| `BIOPORTAL_MCP_URL` | Backend connection URL; defaults to `http://127.0.0.1:8004/mcp` |
| `BIOPORTAL_MAX_TOOL_ROUNDS` | Maximum BioPortal tool-call rounds per model completion; defaults to 3 |
| `PUBMED_MCP_ENABLED` | Allow Meta generation to search PubMed and retrieve citations/abstracts |
| `PUBMED_MCP_URL` | Backend connection URL; defaults to `http://127.0.0.1:8005/mcp` |
| `PUBMED_MAX_TOOL_ROUNDS` | Maximum PubMed tool-call rounds per model completion; defaults to 3 |
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

## ClinicalTrials.gov MCP server

`clinicalgov-mcp` is a standalone read-only service with its own Python package, dependencies, tests, container, and runtime configuration. It does not import or run inside the FastAPI backend. It exposes bounded study search, NCT-record lookup, API/data-version information, and a guarded generic read tool over the public [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api).

Docker Compose runs it as a separate service on `http://localhost:8003/mcp` and injects `http://clinicalgov-mcp:8003/mcp` into the API container. The backend advertises only its focused search, study lookup, and API-info tools to the Meta model. Registry responses are treated as untrusted reference data, and study registration is not treated as evidence of safety, efficacy, or regulatory approval.

Install and run the service independently over stdio:

```powershell
cd clinicalgov-mcp
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
clinicalgov-mcp
```

Or run its network service without the rest of the stack:

```powershell
clinicalgov-mcp --transport streamable-http --host 127.0.0.1 --port 8003
# or, from the repository root:
docker compose up --build clinicalgov-mcp
```

| Variable | Purpose |
| --- | --- |
| `CLINICALGOV_API_BASE_URL` | Public registry API v2 base URL |
| `CLINICALGOV_API_TIMEOUT_SECONDS` | Outbound registry timeout; defaults to 30 seconds |
| `CLINICALGOV_MCP_TRANSPORT` | `stdio` locally or `streamable-http` for a network service |
| `CLINICALGOV_MCP_HOST` / `CLINICALGOV_MCP_PORT` | HTTP bind address and port; local defaults are `127.0.0.1:8003` |

When enabled, the model may derive search terms from submitted source material and send them to public ClinicalTrials.gov, openFDA, NCBO BioPortal, or PubMed APIs. The UI acknowledgement discloses this behavior; keep confidential identifiers out of inputs as well as PHI.

## openFDA MCP server

`openfda_mcp` is a standalone, read-only service for public FDA drug, device, food,
cosmetic, tobacco, and animal/veterinary datasets. Docker Compose exposes it locally
at `http://localhost:8765/mcp` and gives the API container the internal URL
`http://openfda-mcp:8000/mcp`. The Meta model can discover datasets, search records,
perform exact lookups, and aggregate field values through its five allowlisted tools.

Set `OPENFDA_API_KEY` in the root `.env` for regular use, then start the service:

```powershell
docker compose up --build -d openfda-mcp
```

See [`openfda_mcp/README.md`](openfda_mcp/README.md) for tool, security, and local
development details. openFDA data is untrusted reference material, not medical
advice; adverse-event counts do not establish causality, incidence, or risk.

## NCBO BioPortal MCP server

`bioportal-mcp` is a standalone, read-only service for the official [NCBO BioPortal REST API](https://data.bioontology.org/documentation). It exposes focused tools for ontology metadata, class search and lookup, hierarchy and mapping traversal, text annotation, and ontology recommendation. The backend advertises those focused tools to the Meta model but does not expose the service's status tool.

Create a BioPortal account, copy the API key shown on the account page, and set it in the root `.env` file:

```dotenv
BIOPORTAL_API_KEY=your-bioportal-api-key
```

Then run the network service with the stack or by itself:

```powershell
docker compose up --build bioportal-mcp
```

MCP clients connect at `http://localhost:8004/mcp`. BioPortal requires its documented `Authorization: apikey token=...` header; the key remains in the service process and is never returned by a tool. Class lookups require the full class `@id` IRI returned by search. The service percent-encodes that IRI as one path segment, as required by BioPortal's class endpoints.

| Variable | Purpose |
| --- | --- |
| `BIOPORTAL_API_KEY` | BioPortal account API key; required for data requests |
| `BIOPORTAL_API_BASE_URL` | REST base URL; defaults to `https://data.bioontology.org` |
| `BIOPORTAL_API_TIMEOUT_SECONDS` | Outbound request timeout; defaults to 30 seconds |
| `BIOPORTAL_MCP_TRANSPORT` | `stdio` locally or `streamable-http` for a network service |
| `BIOPORTAL_MCP_HOST` / `BIOPORTAL_MCP_PORT` | HTTP bind address and port; local defaults are `127.0.0.1:8004` |

Only send synthetic or de-identified text to the annotation tool. BioPortal results are external reference data: labels, mappings, and annotations do not establish clinical truth, regulatory suitability, or semantic equivalence.

## PubMed MCP server

`pubmed-mcp` is a standalone, read-only service that uses the official NCBI Entrez E-utilities. It follows the same package/container structure as `cdisc-mcp`, but accounts for PubMed's API contract: every request includes the configured `tool` and contact `email`, the optional API key changes the upstream rate limit, ESearch returns JSON, and EFetch returns XML that the service converts into structured citations and abstracts.

Set a real contact email before use. An NCBI API key is optional but recommended for regular traffic:

```dotenv
PUBMED_EMAIL=you@example.com
PUBMED_API_KEY=
```

Docker Compose exposes the service at `http://localhost:8005/mcp` and injects `http://pubmed-mcp:8005/mcp` into the API container. The Meta model receives only the focused `pubmed_search` and `pubmed_get_articles` tools; the service's configuration/status tool is not exposed to generation.

```powershell
docker compose up --build pubmed-mcp
```

See [`pubmed-mcp/README.md`](pubmed-mcp/README.md) for local installation, limits, and tool details. PubMed abstracts are bibliographic reference data rather than full text or medical advice; outputs preserve PMID and DOI for verification.

## Workbench MCP server and direct editing API

The standalone `workbench-mcp` package presents the five registered use cases to MCP clients. Its tools discover contracts, submit synthetic/de-identified text jobs, poll history, and apply complete structured-result revisions. PDF, DOCX, and XLSX submissions remain on the web UI or multipart API so the MCP service never receives host file paths.

The corresponding REST interfaces are:

- `GET /api/v1/use-cases` and `GET /api/v1/use-cases/{id}` for metadata and JSON Schema
- `GET /api/v1/agents` and `GET /api/v1/agents/{use-case}` for specialist agent and tool contracts
- `POST /api/v1/jobs/{use-case}` for generation
- `PUT /api/v1/jobs/{id}/edc-source-spec` to approve normalized EDC metadata and draft domain mappings
- `PUT /api/v1/jobs/{id}/sdtm-domain-mapping` to approve domain mappings and draft variable/VLM mappings
- `PUT /api/v1/jobs/{id}/sdtm-variable-mapping` to approve variable/VLM mappings and generate rules/code
- `GET /api/v1/jobs/{id}` for status and results
- `GET /api/v1/jobs/{id}/agent` for a sanitized agent-turn and source-coverage trace
- `PUT /api/v1/jobs/{id}/result` for human revision and deterministic artifact rebuilding

Repository-local Codex skills under `.codex/skills/` describe how an agent coordinates these Workbench MCP tools with the read-only CDISC Library MCP tools where standards metadata is needed. Each skill includes `agents/openai.yaml` metadata that declares its local MCP dependencies.

After the Compose services are running, reload the repository in Codex and invoke a workflow directly:

```text
Use $clinical-protocol-extraction to extract this synthetic protocol.
Use $clinical-document-generation to draft a statistical analysis plan.
Use $clinical-edc-design to design an EDC specification from this protocol.
Use $clinical-sdtm-artifacts to generate draft SDTM artifacts.
Use $clinical-tlf-artifacts to generate TLF shells and R/SAS scaffolds.
```

Text inputs can be submitted through the Workbench MCP adapter. Workflows that require PDF, DOCX, or XLSX files continue to use the multipart REST API or web interface; the skill still uses MCP to discover the live backend contract, monitor the job, and apply schema-validated revisions.

## Tests

```powershell
cd backend
pytest

cd ..\frontend
npm test
npm run build

cd ..\cdisc-mcp
pytest

cd ..\clinicalgov-mcp
pytest

cd ..\openfda_mcp
uv run pytest

cd ..\bioportal-mcp
pytest

cd ..\pubmed-mcp
pytest
```

Set `RUN_META_INTEGRATION=1` to opt into the live API smoke test. Normal automated tests use an injected test double that is not available in the running application.

Set `RUN_CDISC_INTEGRATION=1` to opt into a live `/mdr/products` smoke test. It also requires `CDISC_LIBRARY_API_KEY`. Normal tests use a mock HTTP transport and do not call CDISC Library.

Set `RUN_CLINICALGOV_INTEGRATION=1` to opt into live API version and known-study checks. ClinicalTrials.gov does not require credentials; normal tests use a mock HTTP transport.

Set `RUN_BIOPORTAL_INTEGRATION=1` to opt into a live NCIT ontology metadata check. It also requires `BIOPORTAL_API_KEY`; normal tests use a mock HTTP transport.

Set `RUN_PUBMED_INTEGRATION=1` and `PUBMED_EMAIL` to opt into a live PubMed search. Normal tests use mocked ESearch JSON and EFetch XML and do not call NCBI.

The standalone `samples/generate_blank_crf.py` helper can also create `samples/blank-crf.pdf` for use outside the running application.

## Standards posture

SDTM outputs are labeled for SDTMIG 3.4 and Define-XML 2.1, but this repository does not distribute CDISC standards content and does not claim conformance. XML is checked for well-formedness and internal references only. All generated programs contain review markers and are never executed by the application.
