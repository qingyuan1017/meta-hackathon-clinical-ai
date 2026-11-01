# Clinical AI Artifact Workbench

A local, single-user hackathon application that uses Meta's OpenAI-compatible API to turn synthetic or de-identified clinical-study inputs into draft clinical artifacts.

> **Important:** This software is a demonstration. Outputs are not validated for regulatory submission, are not medical advice, and require review by qualified clinical, statistical, data-management, and programming professionals. Do not upload PHI or identifiable patient data.

## Included workflows

- Protocol extraction to structured JSON, Markdown, and CDISC USDM 4.0 JSON accepted only after the complete CORE conformance gate passes
- Ten clinical document templates with DOCX and PDF output
- EDC build specifications and edit checks in JSON and XLSX
- SDTM mapping, deterministic per-domain R/SAS programs, optional isolated R execution/XPT output, annotated CRF, Define-XML review, validation triage, and draft cSDRG
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

Every `POST /api/v1/jobs/{workflow}` call runs the workflow's specialist-agent convention. Protocol extraction first runs three parallel sub-agents for design/endpoints, conduct/eligibility, and safety/ambiguities; its lead agent then rereads the original source and reconciles their drafts into the only accepted result. The Codex skill and all four backend protocol agents use `backend/app/agents/protocol_extraction/extraction_policy.md` as their shared clinical extraction policy. SDTM uses three ordered stages: domain disposition, variable/value-level lineage with minor derivations, and record construction plus target-variable implementation expressions. TLF uses an ordered three-stage specialist pipeline. The remaining workflows use one specialist loop. Every agent must inspect the live contract, read every available source chunk, use at most one tool per turn, and submit a schema-valid result before deterministic rendering begins. The shared runtime checks the complete source before the first model call: if every chunk cannot be read within both the configured chunk bound and turn budget, the stage fails closed and records that no partial model execution occurred. XLSX parsing applies the same rule at its configured per-sheet row bound. Recognized SDTM EDC JSON metadata is parsed deterministically; later SDTM stages use a complete compact dataset inventory and target-domain batches rather than serializing a large approved object back through a truncated text prefix. Lead progress is saved under `data/jobs/<job-id>/agent/progress.json`; traces contain no API credential and are removed when the job is deleted.

Every staged human-review gate uses the same scoped patch transaction. The reviewer first selects the affected JSON paths or, for SDTM, the affected source datasets, target domains, variables, and optional variable fields. The server saves the currently edited draft as an immutable baseline, asks the stage agent for a candidate, discards every candidate difference outside that confirmed scope, validates the complete result, and presents the exact before/after operations. Nothing is merged until the reviewer explicitly accepts the patch. Acceptance uses an optimistic revision hash and a three-way merge, so unrelated edits made after generation are preserved while edits to the same path produce a visible conflict and remain unapplied. Rejection leaves the draft unchanged. A pending patch blocks stage approval, and each request, proposal, decision, and conflict is retained under `data/jobs/<job-id>/reviews/<transaction-id>/`. The workflow-neutral JSON-pointer mechanism covers every registered staged review gate; SDTM adds semantic selectors and reruns only selected variable domains. The currently registered gates are the three SDTM stages and the three TLF stages.

Protocol rendering maps the reviewed summary into the official CDISC USDM 4.0 API model and first validates it with CDISC's pinned `usdm` reference package. It then runs the full 207-rule USDM 4.0 set bundled with the official CDISC CORE 0.17.1 release. The gate fails closed for findings, execution errors, unknown statuses, incomplete reports, runtime failures, and technical skips; only raw skips explicitly reported as `Outside scope` are accepted as non-applicable. A successful bundle contains `usdm.json`, the unmodified official `core-report.json`, and the Workbench policy result `core-conformance.json`. A failed job retains those diagnostics for review but never labels the USDM conformant.

The API image fetches the official CORE v0.17.1 source at pinned release commit `2a90a3872a7e3b07c15abe84744026c94a7a04b0`, including its release cache, and installs `cdisc-rules-engine==0.17.1`. Local non-container runs must set `CORE_CLI_PATH` to the matching checked-out `core.py`. Changing the engine or cache requires an explicit ruleset-count and policy review; silently updating the cache would make conformance results non-reproducible.

The SDTM use case has three sequential human review gates. EDC JSON/XLSX is required; a blank CRF PDF is optional for code-only generation and is needed only when an annotated CRF should be produced. JSON normalization parses the complete document and recognizes common `datasets`/`domains`/`tables`/`forms` layouts, dictionary layouts, and unfamiliar nested collections whose dataset and variable metadata can be identified structurally. It never sends only a prefix of a large JSON document to the model. The resulting typed `EDCSourceSpecification` retains exact JSON paths alongside file provenance; missing semantics remain assumptions or unresolved items for the first human approval gate. Small unrecognized JSON and XLSX metadata retain the bounded normalization-agent fallback. Large unrecognized JSON fails explicitly instead of being silently truncated. Domain mapping receives a compact inventory containing every approved dataset and every source-variable identifier. Each source relationship is explicitly `direct`, `stack`, `join`, `split`, or `derived`: stack appends observations as rows, while join adds columns using reviewed keys and cardinality; there is no ambiguous generic merge relationship. Variable mapping then runs one isolated, independently validated agent per target domain, with bounded parallelism controlled by `SDTM_DOMAIN_AGENT_CONCURRENCY`, and proposes source references, metadata, value-level rows, and minor derivations only. Per-domain traces are stored separately and merged into a domain-labeled activity stream; completed results are assembled in the approved domain order and still stop at one combined human approval gate. CDISC reference results retain complete dataset and variable metadata but omit repeated API navigation links before the next model turn. Transient model timeouts retry only the affected domain up to `SDTM_DOMAIN_AGENT_MAX_ATTEMPTS`, retaining accepted outcomes from other domains in the same stage. Per-domain mapping and rule handoffs use the separate `SDTM_DOMAIN_MAX_SOURCE_CHUNKS` complete-read cap so large domains such as QS can include every approved instrument without weakening the global bound for other workflows. The agent must read every chunk, the turn-derived safety bound still applies, and an oversized batch still fails before any model call rather than being truncated. From the variable-mapping gate, a reviewer can explicitly return to domain mapping without invoking a model or losing the current source and variable-mapping baselines. After the revised domain plan is approved, variable mappings for domains whose source/type/relationship signature is unchanged are retained, changed and new domains are regenerated, and removed domains are dropped. Rule/code augmentation uses the same parallel target-domain agent pattern and proposes one ordered `record_plan` for read, stack, join, transpose, filter, deduplicate, and aggregate operations plus target-variable R/SAS right-hand-side expressions. Filter conditions are executable and validated here; approved record preparation is compiled deterministically. Each combined stage is rejected if any approved source, target domain, record plan, or target variable is omitted.

Completed SDTM jobs open a dedicated review workspace instead of a raw JSON-only form. Reviewers can drag raw or existing-SDTM datasets onto target domains, import versioned domain metadata through the configured CDISC Library MCP service, add multiple typed source references to variables and value-level rows, add sponsor SUPP/VLM qualifiers, and inspect derived evidence before or after schema-validated artifact rebuilding. Variable/VLM and Rule & code reviews are separated by target-domain tabs. The Variable & VLM tab owns editable metadata, lineage, VLM, and minor derivations. Rule & code displays the exact generated per-domain R and SAS artifacts as read-only, syntax-highlighted source with line numbers and download access; reviewers revise mappings or rerun the selected domain to rebuild code. After a successful run, a reviewer may rerun either stage for one selected domain: a variable/VLM rerun also refreshes that domain's dependent pipeline and rules, while a rule/code rerun replaces that domain's pipeline and rules together. Both create an exact domain-scoped patch and leave the approved result and downloads untouched until a human accepts it. Acceptance preserves every other domain, regenerates all deterministic artifacts, and resets execution and validation to `not_run` for the changed programs; prior attempt and validation records remain historical evidence only. Rejection preserves the prior result and artifacts. The aCRF tab displays the annotated PDF when a searchable blank CRF was supplied and otherwise explains the intentional not-applicable or OCR-required state.

The completed SDTM workspace now has eight evidence-oriented sections: Domain mapping, Variable & VLM, Rule/program review, Execution, aCRF, Define-XML, Validation, and cSDRG. These sections deliberately keep program generation, execution, validation, and submission-readiness status independent. A skipped or unavailable phase is never displayed as passed.

### Executable SDTM workbench

EDC JSON/XLSX metadata remains required. Blank CRF PDF, raw CSV/XPT datasets, and a Pinnacle 21 CSV/XLSX report are independently optional:

| Input/evidence | Generated | Executed or checked | Evidence meaning |
| --- | --- | --- | --- |
| Metadata only | Mapping XLSX/JSON, R, export-only SAS, Define XML/XSL/HTML/diagnostics, and `csdrg.pdf` | No program execution; validation remains not run | Draft artifacts only; readiness is blocked |
| Searchable blank CRF | `annotated-crf.pdf` plus matched/ambiguous/unmatched coverage JSON | Text matching and visible annotations | Review aid, not OCR or standards validation |
| Raw CSV/XPT | Same artifacts plus isolated R attempt | R runs in the dedicated runner; returned XPTs are reopened and structurally checked | Execution evidence, not CDISC conformance |
| Pinnacle 21 report | Original report plus normalized findings | Imported only | Provider/version provenance is retained; import is not a pass |
| Configured local P21 CLI | Provider report and normalized findings | Runs only with administrator-supplied Java and CLI paths | External validation evidence from the configured local software |
| Workbench internal checks | Normalized internal findings | Expected domains/variables, readable XPTs, identifiers, names | Explicitly not Pinnacle 21 or standards validation |

Generated R is deterministic from the approved typed mapping. Model-authored free-form programs are not executed. The renderer accepts only single side-effect-free mapping expressions, permits an allowlist of pure base-R and exported `dplyr` calls, removes review-only inline comments, and generates all file reads and XPT writes itself. Prose-only TODO expressions become typed-neutral `NA` scaffolds while their original text remains in the mapping JSON for review. Shell/subprocess calls, assignment statements, dynamic function calls, package installation, network APIs, path traversal, and external reads are rejected during structured-result validation and again before execution. If deterministic rendering fails after a complete plan has been saved, **Retry same inputs** first validates and rebuilds that preserved plan without another model call; invalid or incomplete plans fall back to normal regeneration.

The `sdtm-runner` service is a separate non-root container with an internal-only Docker network, read-only root filesystem, dropped Linux capabilities, no-new-privileges, a temporary working directory, and CPU/memory/process/file/wall-clock limits. It receives read-only copies of job inputs and writes to a separate output directory. The API container never invokes `Rscript`. The runner image contains a fixed open-source R environment (`dplyr`, `readr`, `haven`, and `tidyr`) and does not install packages during a job.

Each immutable execution attempt records input and program hashes, parent attempt, timestamps, runner/package versions, exit status, sanitized logs, output hashes and summaries, and deterministic checks. Failed missing-column attempts may produce a typed repair against one specific dataset/variable source reference. The reviewer must approve its diff and rationale before deterministic regeneration and rerun; no more than three approved repair attempts are allowed.

aCRF review highlights the source label and adds a callout containing domain, variable, origin, and mapping information. Duplicate labels are `ambiguous`, absent labels are `unmatched`, and both appear in the PDF appendix and navigation list. A PDF without searchable text produces an OCR-required diagnostic and no pretend annotated PDF; OCR is not included.

Define review exposes a safe local HTML rendering, the exact downloadable XML, and diagnostics for XML well-formedness/internal references. The repository does not bundle CDISC XSD or standards content, so full XSD and standards validation remain explicitly `not_run` unless supplied by a separate qualified process.

Pinnacle 21 report import is the dependable integration path. The optional CLI provider checks server-side configuration and returns `unavailable` when Java or Pinnacle 21 is absent. The repository does not download, bundle, reverse engineer, or redistribute either dependency. Finding explanations enter `csdrg.pdf` only after an explicit reviewer approval. Evidence-controlled cSDRG sections cannot be overwritten through the editable source view.

The cumulative `sdtm/evidence-manifest.json` and refreshed bundle preserve input hashes, attempts, outputs, validation records, finding decisions, artifact hashes, limitations, and human approvals. Rebuilding current artifacts does not delete earlier execution or validation evidence.

#### SDTM runner and optional validator configuration

| Variable | Purpose |
| --- | --- |
| `SDTM_RUNNER_URL` | Dedicated runner base URL; Compose uses `http://sdtm-runner:8010` |
| `SDTM_RUNNER_TIMEOUT_SECONDS` | Per-attempt wall-clock request limit; defaults to 180 seconds |
| `PINNACLE21_CLI_PATH` | Optional server-side path to the administrator-supplied Pinnacle 21 Community/CLI JAR |
| `PINNACLE21_JAVA_PATH` | Optional server-side path to a compatible licensed/local Java executable |
| `PINNACLE21_TIMEOUT_SECONDS` | Optional CLI wall-clock limit; defaults to 600 seconds |

Do not put these paths in frontend variables. If the optional validator is unavailable, use report import; an unavailable result is a limitation, not a successful validation.

#### Synthetic DM/AE demo

1. Start the full stack with `docker compose up --build`. Wait for `api`, `web`, and `sdtm-runner` to become healthy.
2. On the dashboard, download **SDTM DM/AE EDC**, **Blank CRF**, **Raw DM**, **Raw AE**, and **P21 report fixture**. All content is fictional and de-identified.
3. Open **Stats programming → SDTM**. Select `sdtm-demo-edc.json` as the required source, the blank CRF in its dedicated field, `RAW_DM.csv` and `RAW_AE.csv` as raw datasets, and optionally the report fixture. Submit and approve source normalization, domain mapping, and variable/VLM mapping in order.
4. Confirm the reviewed mappings use source datasets `RAW_DM` and `RAW_AE`. Inspect dataset/variable/role lineage in Variable & VLM, then review each domain's ordered record pipeline and expressions in Rule & code. Assigned constants such as `STUDYID` deliberately have no raw source. Saving regenerates the per-domain R and export-only SAS programs but does not execute them.
5. Open **Execution** and select **Execute reviewed R**. Inspect the attempt's program/input/output hashes, sanitized logs, runtime metadata, XPT summaries, and structural checks. Download `dm.xpt` and `ae.xpt` from the artifact list.
6. For the repair path, create a second job using the dashboard's **Raw AE mismatch** download instead of Raw AE. It downloads as `RAW_AE.csv` but intentionally contains `AETERM_RAW` while the approved mapping expects `AETERM`. Execute, review the typed `AETERM → AETERM_RAW` proposal, then choose **Approve and rerun**. Both attempts remain visible.
7. Inspect the highlighted aCRF and its coverage sidebar. In Define-XML, switch among **Styled**, **Raw**, and **Diagnostics**; the Raw tab is the exact `define.xml` content.
8. In **Validation**, import the fixture. Disposition one finding, enter an explanation, check **Approve explanation for cSDRG**, and save. Alternatively run the configured local CLI; without local prerequisites the result is truthfully `unavailable`.
9. Open **cSDRG**, inspect/edit the non-evidence narrative, save, and open `csdrg.pdf`. Confirm the approved explanation and execution trace appear while unapproved explanations do not.
10. Contrast with a metadata-only job using only `sdtm-demo-edc.json`: generation succeeds, execution and validation are `not_run`, readiness remains blocked, and R/SAS/cSDRG state that the programs were not tested against raw data.

Known limitations: only CSV/XPT raw inputs and CSV/XLSX Pinnacle 21 exports are supported; OCR is not included; SAS is never executed; the local CLI adapter depends on the installed release's compatible command interface; Define XSD/standards validation requires externally supplied authoritative content; and the workbench does not certify CDISC conformance or submission readiness. Qualified statistical programming and regulatory review remain required.

The TLF use case follows the same staged architecture without using SDTM as an analysis input. It first extracts only source-supported outputs from the SAP or protocol and maps them to optional ADaM metadata and display rules. The job then pauses in a dedicated shell-review workspace; programming augmentation cannot start until the user approves the output inventory and analysis/display shells. After approval, the final stage adds one non-executed R/SAS scaffold per output. Incomplete specifications remain in the package with explicit blockers and TODO markers.

Completed TLF jobs likewise provide a dedicated three-tab workspace for output inventory, analysis/display metadata, and programming augmentation, with blockers visible throughout review.

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

### Native mobile app

The `mobile/` Expo/React Native app provides a native iOS and Android agent inbox, sanitized execution history, artifact access, and review-gate messaging. Set `EXPO_PUBLIC_API_URL` to an address the phone can reach, or configure the backend address inside the app:

```powershell
cd mobile
npm install
npm start
```

See [`mobile/README.md`](mobile/README.md) for physical-device networking and native build instructions.

## Meta configuration

| Variable | Purpose |
| --- | --- |
| `META_API_KEY` | Server-side Meta API credential |
| `META_API_BASE_URL` | OpenAI-compatible Meta Model API endpoint; defaults to `https://api.meta.ai/v1` |
| `META_MODEL` | Exact model ID enabled for the account |
| `AGENT_MAX_TURNS` | Maximum turns for one specialist-agent run; defaults to 20 |
| `AGENT_MAX_REMOTE_TOOL_CALLS` | Maximum optional MCP calls per agent run; defaults to 6 |
| `SDTM_DOMAIN_AGENT_CONCURRENCY` | Maximum simultaneous SDTM per-domain agents for variable mapping and rule augmentation; defaults to 4 |
| `SDTM_DOMAIN_AGENT_MAX_ATTEMPTS` | Maximum attempts for one SDTM domain after transient model timeouts or connection failures; defaults to 2 and does not rerun accepted domains |
| `SDTM_DOMAIN_MAX_SOURCE_CHUNKS` | Complete-read cap for each SDTM domain agent; defaults to 12 and remains bounded by available agent turns |
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
- `POST /api/v1/jobs/{id}/sdtm-domain-mapping/reopen` to return a variable-mapping review to the domain gate while retaining reconciliation baselines
- `PUT /api/v1/jobs/{id}/sdtm-domain-mapping` to approve domain mappings and draft variable/VLM mappings
- `PUT /api/v1/jobs/{id}/sdtm-variable-mapping` to approve variable/VLM mappings and generate rules/code
- `POST /api/v1/jobs/{id}/sdtm-domain-reruns` with `variable_mapping` or `rule_augmentation` plus one target domain to create a completed-job, human-gated domain patch
- `GET /api/v1/jobs/{id}` for status and results
- `GET /api/v1/jobs/{id}/agent` for a sanitized agent-turn and source-coverage trace
- `POST /api/v1/jobs/{id}/feedback/scope` to suggest a review scope from a comment; the reviewer must still confirm it
- `POST /api/v1/jobs/{id}/feedback` to generate a server-enforced scoped patch against the supplied draft revision
- `POST /api/v1/jobs/{id}/feedback/{transaction-id}/decision` to explicitly accept or reject a pending patch
- `PUT /api/v1/jobs/{id}/result` for human revision and deterministic artifact rebuilding

At the SDTM domain gate, every normalized source dataset must receive an explicit reviewed disposition. Applicable sources may map to one or more target domains; sources outside SDTM tabulation scope are recorded in `unmapped_datasets` with a rationale. The completeness check prevents a source from disappearing because of truncation, but it does not require every source dataset to map to SDTM. A source cannot be both mapped and marked not mapped.

At the variable gate, the review UI presents a matrix with one row per SDTM variable and one column per approved source. Direct, stacked, and joined sources are visibly distinguished; each unique value-level condition creates an additional source-slice column such as `HEIGHT`, `WEIGHT`, or `TEMP`. Selecting any row or source cell opens the detailed editor for target name, label, data type, minor derivation, source references, and VLM rows. Each target variable and value-level row owns zero or more `{dataset, variable, role}` source references, so one target can trace to stacked datasets, join keys, lookups, transpose inputs, or aggregation inputs. `direct` mappings require exactly one source; `assigned` mappings require none; other mapping types retain every contributing source. Assigned constants and source-free derivations use an Assigned/Derived/Protocol/System/Sponsor origin and explicit reviewed logic. Origin labels such as `Assigned` are never treated as raw dataset identifiers. The ordered typed `record_plan` is generated, validated, edited, and rerun with the domain's implementation expressions under Rule & code.

These are breaking mapping-contract changes. Jobs created with the former singular `source_dataset`/`source_field` variable shape or generic `merge` relationship are not silently migrated because doing so could invent lineage or confuse row appends with keyed column additions. Regenerate those jobs through the source, domain, and variable human-approval gates.

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

SDTM outputs are labeled for SDTMIG 3.4 and Define-XML 2.1, but this repository does not distribute CDISC standards content and does not claim conformance. XML is checked for well-formedness and internal references only. Each target domain is rendered to its own `build-<domain>.R` and `build-<domain>.sas` artifact with review markers. When raw data is available, the isolated runner creates an immutable execution copy from the reviewed per-domain R files; SAS remains export-only and is never executed by the application.
