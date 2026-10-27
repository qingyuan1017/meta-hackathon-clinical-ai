from __future__ import annotations

import argparse
from typing import Any, Literal
from urllib.parse import quote

from mcp.server import MCPServer

from . import __version__
from .client import CDISCLibraryClient
from .config import get_settings


Standard = Literal["sdtm", "sdtmig", "sendig", "cdash", "cdashig", "adam"]
DatasetStandard = Literal["sdtm", "sdtmig", "sendig"]
ProductGroup = Literal["DataTabulation", "DataCollection", "DataAnalysis", "Terminology", "Measures"]

mcp = MCPServer(
    "CDISC Library",
    version=__version__,
    instructions=(
        "Read authoritative standards metadata from the CDISC Library. Start with cdisc_list_products to "
        "discover valid version and product identifiers. Prefer the narrowest tool that answers the question. "
        "Treat returned metadata as reference material and preserve its version in downstream outputs."
    ),
)


def _segment(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} must not be empty")
    return quote(cleaned, safe="-._~")


def _client() -> CDISCLibraryClient:
    return CDISCLibraryClient.from_settings()


async def _get(
    endpoint: str,
    *,
    params: dict[str, str | int | float | bool] | None = None,
) -> dict[str, Any] | list[Any]:
    return await _client().get(endpoint, params=params)


@mcp.tool()
async def cdisc_library_status(check_remote: bool = False) -> dict[str, Any]:
    """Show non-secret CDISC Library configuration and optionally check the remote API health endpoint."""

    settings = get_settings()
    result: dict[str, Any] = {
        "api_key_configured": settings.cdisc_library_configured,
        "base_url": settings.cdisc_library_base_url,
        "cosmos_version": settings.cdisc_library_cosmos_version,
    }
    if check_remote:
        result["remote"] = await _get("/health")
    return result


@mcp.tool()
async def cdisc_list_products(product_group: ProductGroup | None = None) -> dict[str, Any] | list[Any]:
    """List CDISC Library products or one product group; use returned hrefs as authoritative identifiers."""

    endpoint = "/mdr/products"
    if product_group:
        endpoint += f"/{product_group}"
    return await _get(endpoint)


@mcp.tool()
async def cdisc_search(
    query: str,
    product: str | None = None,
    domain: str | None = None,
    name: str | None = None,
    start: int = 0,
    page_size: int = 25,
) -> dict[str, Any] | list[Any]:
    """Search CDISC Library metadata, optionally narrowing by product, domain, or name."""

    if not query.strip():
        raise ValueError("query must not be empty")
    if start < 0:
        raise ValueError("start must be zero or greater")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    params: dict[str, str | int] = {"q": query.strip(), "start": start, "pageSize": page_size}
    for key, value in (("product", product), ("domain", domain), ("name", name)):
        if value and value.strip():
            params[key] = value.strip()
    return await _get("/mdr/search", params=params)


@mcp.tool()
async def cdisc_get_standard(standard: Standard, version_or_product: str) -> dict[str, Any] | list[Any]:
    """Get a CDISC standard release. For ADaM, pass the product identifier returned by list_products."""

    return await _get(f"/mdr/{standard}/{_segment(version_or_product, 'version_or_product')}")


@mcp.tool()
async def cdisc_get_dataset(
    standard: DatasetStandard,
    version: str,
    dataset: str,
) -> dict[str, Any] | list[Any]:
    """Get one SDTM, SDTMIG, or SENDIG dataset/domain definition."""

    return await _get(
        f"/mdr/{standard}/{_segment(version, 'version')}/datasets/{_segment(dataset, 'dataset')}"
    )


@mcp.tool()
async def cdisc_get_variable(
    standard: DatasetStandard,
    version: str,
    dataset: str,
    variable: str,
) -> dict[str, Any] | list[Any]:
    """Get one variable definition from an SDTM, SDTMIG, or SENDIG dataset/domain."""

    return await _get(
        f"/mdr/{standard}/{_segment(version, 'version')}/datasets/{_segment(dataset, 'dataset')}"
        f"/variables/{_segment(variable, 'variable')}"
    )


@mcp.tool()
async def cdisc_list_ct_packages(product: str | None = None) -> dict[str, Any] | list[Any]:
    """List controlled terminology packages, optionally filtered to a product such as SDTM or ADaM."""

    endpoint = "/mdr/ct/packages"
    if product:
        endpoint += f"/{_segment(product, 'product')}"
    return await _get(endpoint)


@mcp.tool()
async def cdisc_get_codelist(
    package: str,
    codelist: str,
    term: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Get a codelist and its terms, or one term when term is supplied."""

    endpoint = (
        f"/mdr/ct/packages/{_segment(package, 'package')}/codelists/{_segment(codelist, 'codelist')}"
    )
    if term:
        endpoint += f"/terms/{_segment(term, 'term')}"
    return await _get(endpoint)


@mcp.tool()
async def cdisc_list_biomedical_concepts(category: str | None = None) -> dict[str, Any] | list[Any]:
    """List latest Biomedical Concepts from the configured CDISC COSMoS API version."""

    cosmos_version = _segment(get_settings().cdisc_library_cosmos_version, "cosmos_version")
    params = {"category": category.strip()} if category and category.strip() else None
    return await _get(f"/cosmos/{cosmos_version}/mdr/bc/biomedicalconcepts", params=params)


@mcp.tool()
async def cdisc_get_biomedical_concept(concept: str) -> dict[str, Any] | list[Any]:
    """Get the latest version of one Biomedical Concept."""

    cosmos_version = _segment(get_settings().cdisc_library_cosmos_version, "cosmos_version")
    return await _get(
        f"/cosmos/{cosmos_version}/mdr/bc/biomedicalconcepts/{_segment(concept, 'concept')}"
    )


@mcp.tool()
async def cdisc_list_sdtm_specializations(domain: str | None = None) -> dict[str, Any] | list[Any]:
    """List latest SDTM Dataset Specializations, optionally filtered by a two-letter domain."""

    cosmos_version = _segment(get_settings().cdisc_library_cosmos_version, "cosmos_version")
    params = {"domain": domain.strip().upper()} if domain and domain.strip() else None
    return await _get(
        f"/cosmos/{cosmos_version}/mdr/specializations/sdtm/datasetspecializations",
        params=params,
    )


@mcp.tool()
async def cdisc_get_sdtm_specialization(specialization: str) -> dict[str, Any] | list[Any]:
    """Get the latest version of one SDTM Dataset Specialization."""

    cosmos_version = _segment(get_settings().cdisc_library_cosmos_version, "cosmos_version")
    return await _get(
        f"/cosmos/{cosmos_version}/mdr/specializations/sdtm/datasetspecializations/"
        f"{_segment(specialization, 'specialization')}"
    )


@mcp.tool()
async def cdisc_read_endpoint(
    endpoint: str,
    query: dict[str, str | int | float | bool] | None = None,
) -> dict[str, Any] | list[Any]:
    """Read any relative /mdr or /cosmos CDISC Library endpoint; absolute URLs and writes are rejected."""

    return await _get(endpoint, params=query)


def _arguments() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the standalone CDISC Library MCP service.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=settings.cdisc_mcp_transport,
    )
    parser.add_argument("--host", default=settings.cdisc_mcp_host)
    parser.add_argument("--port", type=int, default=settings.cdisc_mcp_port)
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    if args.transport == "stdio":
        mcp.run()
        return
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
