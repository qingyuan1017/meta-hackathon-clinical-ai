# PubMed MCP Service

Standalone, read-only Model Context Protocol service for PubMed through the official NCBI Entrez E-utilities API. It follows the repository's CDISC MCP package layout while handling PubMed's required request identity, optional API key, rate limits, JSON ESearch responses, and XML EFetch records.

## Configuration

Set `PUBMED_EMAIL` to a real contact address. NCBI asks software clients to send both `tool` and `email` with every E-utilities request. `PUBMED_API_KEY` is optional but recommended: NCBI permits up to 3 requests per second without a key and 10 per second with one by default. The client throttles itself to the applicable limit and retries transient failures.

See the official [Entrez E-utilities documentation](https://www.ncbi.nlm.nih.gov/books/NBK25501/) and [NCBI policies and disclaimers](https://www.ncbi.nlm.nih.gov/home/about/policies/). Tool results include these policy links.

```dotenv
PUBMED_EMAIL=you@example.com
PUBMED_API_KEY=
```

Do not expose the API key in browser variables or commit it to source control.

## Tools

- `pubmed_search` searches with native PubMed syntax, optional date bounds, bounded paging, and returns structured citations plus available abstracts.
- `pubmed_get_articles` retrieves up to 20 known PMIDs in one EFetch call.
- `pubmed_status` reports non-secret configuration and can optionally query PubMed API metadata.

The service preserves PMID and DOI identifiers. It labels abstracts as bibliographic reference data, not full text or medical advice. PubMed ESearch exposes at most the first 10,000 results, so broad searches should be segmented with date ranges.

## Run locally over stdio

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pubmed-mcp
```

## Run over Streamable HTTP

```powershell
pubmed-mcp --transport streamable-http --host 127.0.0.1 --port 8004
```

Connect an MCP client to `http://127.0.0.1:8004/mcp`. From the repository root, Docker Compose starts the same service with `docker compose up --build pubmed-mcp`.

## Test

```powershell
pytest
```

Set `RUN_PUBMED_INTEGRATION=1` and `PUBMED_EMAIL` to include the live API smoke test. Normal tests use mocked HTTP and do not call NCBI.
