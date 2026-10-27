from __future__ import annotations

import argparse
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import __version__
from .client import PubMedClient, PubMedError
from .config import get_settings

SortOrder = Literal["relevance", "pub_date", "Author", "JournalName"]
DateType = Literal["pdat", "edat", "mdat"]
SOURCE_NOTICE = (
    "PubMed records are public bibliographic reference data from NCBI. Abstract text may be "
    "copyrighted. Cite PMID/DOI, quote sparingly, appraise the underlying study, and do not treat "
    "a search result as proof of efficacy or safety. This service is not medical advice."
)


def _with_notice(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "source_notice": SOURCE_NOTICE,
        "ncbi_eutilities_documentation": "https://www.ncbi.nlm.nih.gov/books/NBK25501/",
        "ncbi_policies": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
    }


def create_server(client: PubMedClient | None = None) -> MCPServer:
    pubmed = client or PubMedClient.from_settings()
    server = MCPServer(
        "PubMed",
        version=__version__,
        instructions=(
            "Search and retrieve biomedical citations from PubMed through the official NCBI Entrez "
            "E-utilities. Use pubmed_search to discover evidence and pubmed_get_articles when PMIDs "
            "are already known. Preserve PMID and DOI in downstream work, distinguish abstracts from "
            f"full text, and critically appraise sources. {SOURCE_NOTICE}"
        ),
    )

    @server.tool()
    async def pubmed_status(check_remote: bool = False) -> dict[str, Any]:
        """Show non-secret NCBI configuration and optionally read current PubMed API metadata."""

        result: dict[str, Any] = {
            "email_configured": bool(pubmed.email),
            "api_key_configured": bool(pubmed.api_key),
            "api_base_url": pubmed.base_url.rstrip("/"),
            "max_results": pubmed.max_results,
            "rate_limit_requests_per_second": 10 if pubmed.api_key else 3,
        }
        if check_remote:
            try:
                result["remote"] = await pubmed.api_info()
            except PubMedError as exc:
                raise ToolError(str(exc)) from exc
        return result

    @server.tool()
    async def pubmed_search(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=2000,
                description="PubMed query using words, phrases, Boolean operators, and field tags.",
            ),
        ],
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        offset: Annotated[int, Field(ge=0, le=9999)] = 0,
        sort: SortOrder = "relevance",
        date_type: DateType | None = None,
        min_date: Annotated[
            str | None, Field(description="Start date as YYYY, YYYY/MM, or YYYY/MM/DD.")
        ] = None,
        max_date: Annotated[
            str | None, Field(description="End date as YYYY, YYYY/MM, or YYYY/MM/DD.")
        ] = None,
    ) -> dict[str, Any]:
        """Search PubMed and return matching citations plus available abstracts.

        PubMed syntax is supported, for example `asthma[Title] AND randomized controlled trial[pt]`.
        Date bounds must be supplied together. PubMed ESearch exposes only the first 10,000 results;
        narrow broad queries with date ranges rather than paging beyond that cap.
        """

        try:
            return _with_notice(
                await pubmed.search(
                    query,
                    limit=limit,
                    offset=offset,
                    sort=sort,
                    date_type=date_type,
                    min_date=min_date,
                    max_date=max_date,
                )
            )
        except (PubMedError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    async def pubmed_get_articles(
        pmids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=20,
                description="One to 20 PubMed identifiers returned by PubMed search or a citation.",
            ),
        ],
    ) -> dict[str, Any]:
        """Retrieve structured citation metadata and available abstracts for known PMIDs."""

        try:
            articles = await pubmed.fetch(pmids)
            normalized_pmids = [PubMedClient.normalize_pmid(value) for value in pmids]
            returned_pmids = {article["pmid"] for article in articles}
            return _with_notice(
                {
                    "requested_pmids": normalized_pmids,
                    "missing_pmids": [
                        pmid for pmid in normalized_pmids if pmid not in returned_pmids
                    ],
                    "returned_count": len(articles),
                    "articles": articles,
                }
            )
        except (PubMedError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return server


mcp = create_server()


def _arguments() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Run the standalone PubMed MCP service."
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=settings.pubmed_mcp_transport,
    )
    parser.add_argument("--host", default=settings.pubmed_mcp_host)
    parser.add_argument("--port", type=int, default=settings.pubmed_mcp_port)
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
