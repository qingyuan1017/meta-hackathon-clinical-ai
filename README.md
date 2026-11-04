# SDTM Artifact Workbench

An agent-assisted workspace for turning synthetic or de-identified EDC metadata into reviewable CDISC SDTM deliverables. The submission centers on one end-to-end workflow: source review, SDTM mapping, deterministic program generation, isolated R execution, validation review, and evidence packaging.

> **Demonstration software:** Outputs are drafts, not validated regulatory submissions or medical advice. Use only synthetic or de-identified data with no PHI. Qualified clinical data-management and statistical-programming reviewers must approve all results.

## What it demonstrates

- Human approval gates for source normalization, domain mapping, and variable/value-level mapping
- Standards-aware metadata lookup through the CDISC Library MCP service
- Deterministic per-domain R and SAS generation from the approved mapping
- Isolated R execution with immutable attempt metadata and XPT structural checks
- Review workspaces for aCRF, Define-XML, validation findings, and cSDRG
- A submission-oriented ZIP with artifacts, evidence, provenance, and limitations
- Scoped AI revision proposals that cannot silently change unapproved parts of a mapping

Other clinical workflows remain in the codebase as experimental extensions, but they are outside this submission's primary scope.

## SDTM workflow

```text
EDC JSON/XLSX
      |
      v
1. Review normalized sources
      |
      v
2. Review source-to-domain disposition
      |
      v
3. Review variable lineage and VLM
      |
      v
Deterministic R/SAS generation
      |
      +---- optional raw CSV/XPT ---> isolated R execution
      |
      +---- optional blank CRF ----> annotated CRF
      |
      +---- optional P21 report ---> validation triage
      v
Define-XML + cSDRG + evidence manifest + submission package
```

The completed workspace separates eight concerns: Domain mapping, Variable & VLM, Rule/program review, Execution, aCRF, Define-XML, Validation, and cSDRG. Generated, executed, validated, and submission-ready are deliberately separate states.

## Quick start

### Prerequisites

- Docker Desktop with Docker Compose
- A Meta API key and an enabled OpenAI-compatible model ID
- Optional: a CDISC Library subscription key for live standards metadata

### Run the stack

```powershell
Copy-Item .env.example .env
```

Set at least these values in `.env`:

```dotenv
META_API_KEY=your-key
META_MODEL=your-model-id
CDISC_LIBRARY_API_KEY=your-optional-cdisc-key
```

Then start the application:

```powershell
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The API is available at [http://localhost:8000](http://localhost:8000), and its health endpoint is `/api/v1/health`.

Credentials stay server-side. Generation is disabled until `META_API_KEY` and `META_MODEL` are configured.

## Demo data

The `samples/` directory contains a small, synthetic SDTM demonstration:

| File | Use |
| --- | --- |
| `sdtm-demo-edc.json` | Required EDC metadata |
| `RAW_DM.csv`, `RAW_AE.csv` | Optional raw data for execution |
| `RAW_AE-mismatch.csv` | Intentional mismatch for repair/review demonstration |
| `pinnacle21-demo-report.csv` | Optional validation-report import |
| `generate_blank_crf.py` | Creates an optional searchable blank CRF |

Create the sample CRF after installing the backend development dependencies, or run the helper in a compatible Python environment with ReportLab:

```powershell
python samples/generate_blank_crf.py
```

In the web application, choose **CDISC SDTM**, upload `samples/sdtm-demo-edc.json`, and optionally add the raw datasets, generated `samples/blank-crf.pdf`, and demo validation report.

## Inputs and outputs

| Input | Required | Purpose |
| --- | --- | --- |
| EDC metadata (`.json` or `.xlsx`) | Yes | Source datasets, variables, labels, and provenance |
| Raw datasets (`.csv` or `.xpt`) | No | Isolated execution and structural output checks |
| Searchable blank CRF (`.pdf`) | No | Visible annotation and coverage review |
| Pinnacle 21 report (`.csv` or `.xlsx`) | No | Imported external validation evidence |

Primary outputs include mapping JSON/XLSX, per-domain R and SAS programs, XPT datasets when execution succeeds, annotated CRF when supplied, Define-XML with a local review stylesheet, cSDRG PDF, validation diagnostics, an evidence manifest, and `sdtm-submission-package.zip`.

## Architecture

| Component | Responsibility |
| --- | --- |
| `frontend/` | Next.js review workspace |
| `backend/` | FastAPI orchestration, review gates, schemas, and deterministic rendering |
| `sdtm-runner/` | Network-isolated, non-root R execution service |
| `cdisc-mcp/` | Read-only CDISC Library integration |
| `workbench-mcp/` | MCP interface for job submission, monitoring, and revision |
| `minio/` | Durable S3-compatible input storage for Compose |
| `scripts/submit_sdtm.py` | Client-side multipart uploader for automation and Muse Code |

The model proposes structured mappings; it does not author free-form executable programs. Approved typed mappings are validated and compiled into programs by deterministic application code. The runner has an internal-only network, read-only root filesystem, dropped capabilities, and resource limits.

## Command-line submission

With the stack running, submit local files directly:

```powershell
python scripts/submit_sdtm.py `
  --metadata samples/sdtm-demo-edc.json `
  --raw samples/RAW_DM.csv samples/RAW_AE.csv `
  --acknowledge-deidentified
```

Muse Code setup and the repository-local clinical skill are documented in [`MUSE_CODE.md`](MUSE_CODE.md).

## Tests

Python 3.12 is required for the backend services. From the repository root, create one development environment and install the tested packages:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]" -e ".\cdisc-mcp[dev]" -e ".\workbench-mcp[dev]" -e ".\sdtm-runner[dev]"

python -m pytest backend/tests
python -m pytest cdisc-mcp/tests
python -m pytest workbench-mcp/tests
python -m pytest sdtm-runner/tests

cd frontend
npm ci
npm test
npm run build
```

Live API integration tests are opt-in and require their corresponding environment variables. Normal tests use doubles or mocked transports.

## Standards and validation posture

Artifacts target SDTMIG 3.4 and Define-XML 2.1. The repository does not redistribute CDISC standards content and does not claim CDISC conformance. Internal checks cover schema validity, lineage completeness, XML well-formedness and references, readable XPTs, expected domains/variables, hashes, and provenance.

Pinnacle 21 evidence is imported from a supplied report or produced only when an administrator configures a local licensed CLI. A skipped, unavailable, or not-run check is never displayed as passed. Every generated package retains its known limitations and human-approval evidence.

## Additional documentation

- [`MUSE_CODE.md`](MUSE_CODE.md) — Muse Code and MCP workflow
- [`mobile/README.md`](mobile/README.md) — optional Expo client
- [`cdisc-mcp/README.md`](cdisc-mcp/README.md) — CDISC Library service
- [`workbench-mcp/README.md`](workbench-mcp/README.md) — Workbench MCP service
- [`minio/README.md`](minio/README.md) — local object storage

## License

See [`LICENSE`](LICENSE).
