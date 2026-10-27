from __future__ import annotations

import argparse
import re
from typing import Any, Literal
from urllib.parse import quote

from mcp.server import MCPServer

from . import __version__
from .client import BioPortalClient
from .config import get_settings


ClassRelation = Literal["parents", "children", "ancestors", "descendants", "mappings"]
RecommenderInputType = Literal[1, 2]
ACRONYM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
DEFAULT_CLASS_FIELDS = [
    "prefLabel",
    "synonym",
    "definition",
    "notation",
    "cui",
    "semanticType",
    "obsolete",
    "prefixIRI",
    "childrenCount",
    "hasChildren",
]
DEFAULT_SEARCH_FIELDS = [
    "prefLabel",
    "synonym",
    "definition",
    "notation",
    "cui",
    "semanticType",
]
DEFAULT_ONTOLOGY_FIELDS = [
    "acronym",
    "name",
    "description",
    "ontologyType",
    "group",
    "hasDomain",
    "viewingRestriction",
]

mcp = MCPServer(
    "NCBO BioPortal",
    version=__version__,
    instructions=(
        "Read biomedical ontology metadata from the NCBO BioPortal API. Search first to discover ontology "
        "acronyms and class IRIs, then pass the returned class @id unchanged to class and hierarchy tools. "
        "Treat labels, definitions, mappings, and annotations as external reference data rather than clinical "
        "facts; preserve ontology acronyms and class identifiers in downstream outputs."
    ),
)


def _client() -> BioPortalClient:
    return BioPortalClient.from_settings()


async def _get(
    endpoint: str,
    *,
    params: dict[str, str | int | float | bool] | None = None,
) -> dict[str, Any] | list[Any]:
    return await _client().get(endpoint, params=params)


def _acronym(value: str, label: str = "ontology") -> str:
    candidate = value.strip().upper()
    if not ACRONYM.fullmatch(candidate):
        raise ValueError(f"{label} must be a BioPortal ontology acronym")
    return candidate


def _acronyms(values: list[str] | None) -> str | None:
    if not values:
        return None
    if len(values) > 20:
        raise ValueError("ontologies may contain at most 20 acronyms")
    return ",".join(_acronym(value, "each ontology") for value in values)


def _class_id(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 2000:
        raise ValueError("class_id must contain a class IRI of at most 2000 characters")
    if not url_is_http(candidate):
        raise ValueError("class_id must be the absolute http or https IRI returned by BioPortal")
    return quote(candidate, safe="")


def url_is_http(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _fields(values: list[str] | None, default: list[str]) -> str:
    selected = values or default
    if not 1 <= len(selected) <= 20:
        raise ValueError("include_fields must contain between 1 and 20 attribute names")
    cleaned: list[str] = []
    for value in selected:
        candidate = value.strip()
        if not candidate or not candidate.replace("_", "").isalnum():
            raise ValueError("each include field must be a BioPortal attribute name")
        cleaned.append(candidate)
    return ",".join(cleaned)


def _text(value: str, label: str, maximum: int = 5000) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{label} must not be empty")
    if len(candidate) > maximum:
        raise ValueError(f"{label} must be {maximum} characters or fewer")
    return candidate


def _page(page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page must be 1 or greater")
    if not 1 <= page_size <= 50:
        raise ValueError("page_size must be between 1 and 50")


@mcp.tool()
async def bioportal_status(check_remote: bool = False) -> dict[str, Any]:
    """Show non-secret BioPortal configuration and optionally check access with the NCIT ontology."""

    settings = get_settings()
    result: dict[str, Any] = {
        "api_key_configured": settings.bioportal_configured,
        "base_url": settings.bioportal_api_base_url,
    }
    if check_remote:
        result["remote"] = await _get(
            "/ontologies/NCIT",
            params={
                "include": "acronym,name",
                "display_context": False,
                "display_links": False,
            },
        )
    return result


@mcp.tool()
async def bioportal_get_ontology(
    ontology: str,
    include_fields: list[str] | None = None,
) -> dict[str, Any] | list[Any]:
    """Get metadata for one ontology by acronym, such as NCIT, SNOMEDCT, LOINC, or RXNORM."""

    return await _get(
        f"/ontologies/{_acronym(ontology)}",
        params={
            "include": _fields(include_fields, DEFAULT_ONTOLOGY_FIELDS),
            "display_context": False,
        },
    )


@mcp.tool()
async def bioportal_search_classes(
    query: str,
    ontologies: list[str] | None = None,
    require_exact_match: bool = False,
    require_definitions: bool = False,
    include_obsolete: bool = False,
    include_fields: list[str] | None = None,
    language: str = "en",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any] | list[Any]:
    """Search ontology classes; results contain class @id IRIs for exact lookup and traversal."""

    _page(page, page_size)
    language_code = language.strip().lower()
    if not re.fullmatch(r"[a-z]{2}", language_code):
        raise ValueError("language must be a two-letter ISO 639-1 code")
    params: dict[str, str | int | bool] = {
        "q": _text(query, "query", 500),
        "require_exact_match": require_exact_match,
        "require_definitions": require_definitions,
        "also_search_obsolete": include_obsolete,
        "include": _fields(include_fields, DEFAULT_SEARCH_FIELDS),
        "language": language_code,
        "page": page,
        "pagesize": page_size,
        "display_context": False,
    }
    selected = _acronyms(ontologies)
    if selected:
        params["ontologies"] = selected
    return await _get("/search", params=params)


@mcp.tool()
async def bioportal_get_class(
    ontology: str,
    class_id: str,
    include_fields: list[str] | None = None,
) -> dict[str, Any] | list[Any]:
    """Get one class by ontology acronym and the full class @id IRI returned by BioPortal search."""

    return await _get(
        f"/ontologies/{_acronym(ontology)}/classes/{_class_id(class_id)}",
        params={
            "include": _fields(include_fields, DEFAULT_CLASS_FIELDS),
            "display_context": False,
        },
    )


@mcp.tool()
async def bioportal_get_class_related(
    ontology: str,
    class_id: str,
    relation: ClassRelation,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any] | list[Any]:
    """Get parents, children, ancestors, descendants, or mappings for a class IRI."""

    _page(page, page_size)
    endpoint = (
        f"/ontologies/{_acronym(ontology)}/classes/{_class_id(class_id)}/{relation}"
    )
    include = "classes,process,source" if relation == "mappings" else _fields(
        None, DEFAULT_CLASS_FIELDS
    )
    return await _get(
        endpoint,
        params={
            "include": include,
            "page": page,
            "pagesize": page_size,
            "display_context": False,
        },
    )


@mcp.tool()
async def bioportal_annotate_text(
    text: str,
    ontologies: list[str] | None = None,
    longest_only: bool = True,
    whole_word_only: bool = True,
    exclude_numbers: bool = True,
    exclude_synonyms: bool = False,
    expand_mappings: bool = False,
    hierarchy_levels: int = 0,
    minimum_match_length: int = 3,
    max_results: int = 50,
) -> list[Any]:
    """Annotate synthetic or de-identified biomedical text with BioPortal ontology classes."""

    if not 0 <= hierarchy_levels <= 5:
        raise ValueError("hierarchy_levels must be between 0 and 5")
    if not 1 <= minimum_match_length <= 50:
        raise ValueError("minimum_match_length must be between 1 and 50")
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")
    params: dict[str, str | int | bool] = {
        "text": _text(text, "text"),
        "longest_only": longest_only,
        "whole_word_only": whole_word_only,
        "exclude_numbers": exclude_numbers,
        "exclude_synonyms": exclude_synonyms,
        "expand_mappings": expand_mappings,
        "expand_class_hierarchy": hierarchy_levels > 0,
        "class_hierarchy_max_level": hierarchy_levels,
        "minimum_match_length": minimum_match_length,
        "display_context": False,
    }
    selected = _acronyms(ontologies)
    if selected:
        params["ontologies"] = selected
    result = await _get("/annotator", params=params)
    if not isinstance(result, list):
        raise ValueError("BioPortal returned an unexpected non-list annotator response")
    return result[:max_results]


@mcp.tool()
async def bioportal_recommend_ontologies(
    input_text: str,
    input_type: RecommenderInputType = 1,
    ontologies: list[str] | None = None,
    max_results: int = 10,
) -> list[Any]:
    """Rank ontologies for biomedical text (input_type 1) or comma-separated keywords (input_type 2)."""

    if not 1 <= max_results <= 20:
        raise ValueError("max_results must be between 1 and 20")
    params: dict[str, str | int | bool] = {
        "input": _text(input_text, "input_text"),
        "input_type": input_type,
        "output_type": 1,
        "display_context": False,
    }
    selected = _acronyms(ontologies)
    if selected:
        params["ontologies"] = selected
    result = await _get("/recommender", params=params)
    if not isinstance(result, list):
        raise ValueError("BioPortal returned an unexpected non-list recommender response")
    return result[:max_results]


def _arguments() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the standalone NCBO BioPortal MCP service.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=settings.bioportal_mcp_transport,
    )
    parser.add_argument("--host", default=settings.bioportal_mcp_host)
    parser.add_argument("--port", type=int, default=settings.bioportal_mcp_port)
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
