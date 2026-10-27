# NCBO BioPortal MCP Service

Standalone, read-only Model Context Protocol service for the official NCBO BioPortal REST API. It is packaged and deployed independently from the clinical workbench backend.

The service uses BioPortal's documented `Authorization: apikey token=...` header. Class identifiers are full IRIs and are percent-encoded as a single path segment before class, hierarchy, or mapping requests.

## Configuration

Create a BioPortal account and copy the API key from your account page. Set `BIOPORTAL_API_KEY` in the process environment or in the working directory's `.env` file. Optional settings are documented in `.env.example`.

## Run locally over stdio

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
bioportal-mcp
```

Configure a local MCP host to launch the `bioportal-mcp` executable. Standard output is reserved for the MCP protocol.

## Run as a Streamable HTTP service

```powershell
bioportal-mcp --transport streamable-http --host 127.0.0.1 --port 8004
```

Connect an MCP client to `http://127.0.0.1:8004/mcp`. The service has no inbound authentication, so keep it on a trusted interface or place authentication in front of it before remote deployment.

From the repository root, Docker Compose runs the same service on `http://localhost:8004/mcp`:

```powershell
docker compose up --build bioportal-mcp
```

## Tools

- `bioportal_search_classes` searches terms with bounded pagination and optional ontology filters.
- `bioportal_get_class` retrieves a class using the full `@id` returned by search.
- `bioportal_get_class_related` traverses parents, children, ancestors, descendants, or mappings.
- `bioportal_get_ontology` retrieves ontology metadata by acronym.
- `bioportal_annotate_text` maps synthetic or de-identified text to ontology classes.
- `bioportal_recommend_ontologies` ranks ontologies for text or keywords.
- `bioportal_status` reports non-secret configuration and can verify remote access.

BioPortal content is external reference data. Ontology labels, mappings, and annotations do not by themselves establish clinical truth, regulatory suitability, or semantic equivalence.

## Test

```powershell
pytest
```

Set `RUN_BIOPORTAL_INTEGRATION=1` to include the live NCIT metadata test. The normal suite uses mocked HTTP and does not call BioPortal.
