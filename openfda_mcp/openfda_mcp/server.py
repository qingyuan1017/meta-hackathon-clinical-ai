"""MCP tool definitions for model-friendly openFDA access."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .catalog import ENDPOINTS, endpoint_ids
from .client import OpenFDAClient, OpenFDAError, exact_search, project_records

SAFETY_NOTICE = (
    "openFDA data is for research and informational use only. It is not medical advice and must "
    "not be used alone for diagnosis, treatment, or clinical decisions. Adverse-event reports do "
    "not establish causality or incidence."
)

INSTRUCTIONS = f"""Use these tools to query public FDA datasets through openFDA.

Start with list_openfda_endpoints, then describe_openfda_endpoint before composing a complex query.
Prefer lookup_openfda for an exact field value and search_openfda for openFDA query expressions.
Use selected fields and small limits to keep results focused. Never expose or request an API key.

{SAFETY_NOTICE}
"""


def _tool_error(exc: OpenFDAError) -> ToolError:
    return ToolError(str(exc))


def _with_notice(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "clinical_safety_notice": SAFETY_NOTICE}


def create_server(client: OpenFDAClient | None = None) -> MCPServer:
    """Create an MCP server; a client can be injected for deterministic tests."""
    openfda = client or OpenFDAClient()
    server = MCPServer(
        "openFDA",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    @server.custom_route("/health", methods=["GET"])
    async def health_check(_: Request) -> JSONResponse:
        """Unauthenticated liveness endpoint for container orchestration."""
        return JSONResponse(
            {"status": "ok", "service": "openfda-mcp", "version": __version__}
        )

    @server.tool()
    def list_openfda_endpoints(category: str | None = None) -> dict[str, Any]:
        """List supported openFDA dataset IDs, optionally filtered by category.

        Categories include drug, device, food, cosmetic, tobacco, and animalandveterinary.
        Use a returned dataset ID as the endpoint argument in the other tools.
        """
        ids = endpoint_ids(category)
        if category is not None and not ids:
            categories = sorted({item["category"] for item in ENDPOINTS.values()})
            raise ToolError(
                f"Unknown or empty category '{category}'. "
                f"Available categories: {', '.join(categories)}."
            )
        return _with_notice(
            {
                "endpoints": [
                    {
                        "id": endpoint_id,
                        "title": ENDPOINTS[endpoint_id]["title"],
                        "category": ENDPOINTS[endpoint_id]["category"],
                        "description": ENDPOINTS[endpoint_id]["description"],
                    }
                    for endpoint_id in ids
                ],
                "count": len(ids),
            }
        )

    @server.tool()
    def describe_openfda_endpoint(endpoint: str) -> dict[str, Any]:
        """Describe one dataset, including useful field names and example search expressions."""
        try:
            endpoint_id = openfda.normalize_endpoint(endpoint)
        except OpenFDAError as exc:
            raise _tool_error(exc) from exc
        return _with_notice({"id": endpoint_id, **ENDPOINTS[endpoint_id]})

    @server.tool()
    async def search_openfda(
        endpoint: str,
        search: Annotated[
            str | None,
            Field(
                max_length=2048,
                description=(
                    "openFDA expression such as openfda.brand_name.exact:\"LIPITOR\". "
                    "Omit to retrieve recent/default records."
                ),
            ),
        ] = None,
        limit: Annotated[
            int | None,
            Field(ge=1, le=1000, description="Defaults to 10, capped by server configuration."),
        ] = None,
        skip: Annotated[int, Field(ge=0, le=25000)] = 0,
        sort: Annotated[
            str | None, Field(description="Optional sort in field:asc or field:desc form.")
        ] = None,
        fields: Annotated[
            list[str] | None,
            Field(
                max_length=25,
                description="Optional dotted field paths to return; omit for complete records.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Search records in a supported openFDA dataset.

        This accepts native openFDA query syntax. Call describe_openfda_endpoint for examples.
        Results include upstream metadata and a source URL with the API key removed.
        """
        try:
            effective_limit = limit if limit is not None else min(10, openfda.settings.max_results)
            payload = await openfda.query(
                endpoint, search=search, limit=effective_limit, skip=skip, sort=sort
            )
            return _with_notice(project_records(payload, fields))
        except OpenFDAError as exc:
            raise _tool_error(exc) from exc

    @server.tool()
    async def lookup_openfda(
        endpoint: str,
        field: str,
        value: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[
            int | None,
            Field(ge=1, le=1000, description="Defaults to 10, capped by server configuration."),
        ] = None,
        fields: Annotated[
            list[str] | None,
            Field(max_length=25, description="Optional dotted field paths to return."),
        ] = None,
    ) -> dict[str, Any]:
        """Look up records by one exact field value without writing openFDA query syntax."""
        try:
            query = exact_search(field, value)
            effective_limit = limit if limit is not None else min(10, openfda.settings.max_results)
            payload = await openfda.query(endpoint, search=query, limit=effective_limit)
            return _with_notice(project_records(payload, fields))
        except OpenFDAError as exc:
            raise _tool_error(exc) from exc

    @server.tool()
    async def count_openfda(
        endpoint: str,
        field: str,
        search: Annotated[
            str | None,
            Field(max_length=2048, description="Optional openFDA filter expression."),
        ] = None,
        limit: Annotated[
            int | None,
            Field(ge=1, le=1000, description="Defaults to 100, capped by server configuration."),
        ] = None,
    ) -> dict[str, Any]:
        """Count the most frequent values of a field, optionally within a filtered result set.

        Counts from spontaneous reports describe reporting frequency, not event incidence or risk.
        """
        try:
            effective_limit = limit if limit is not None else min(100, openfda.settings.max_results)
            payload = await openfda.query(
                endpoint, search=search, count=field, limit=effective_limit
            )
            return _with_notice(payload)
        except OpenFDAError as exc:
            raise _tool_error(exc) from exc

    return server


mcp = create_server()

