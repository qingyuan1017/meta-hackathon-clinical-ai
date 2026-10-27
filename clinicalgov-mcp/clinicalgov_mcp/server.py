from __future__ import annotations

import argparse
from typing import Any, Literal

from mcp.server import MCPServer

from . import __version__
from .client import ClinicalTrialsGovClient
from .config import get_settings


OverallStatus = Literal[
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "COMPLETED",
    "WITHDRAWN",
    "UNKNOWN",
]

DEFAULT_SEARCH_FIELDS = [
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "HasResults",
    "Condition",
    "InterventionType",
    "InterventionName",
    "Phase",
    "EnrollmentCount",
    "LeadSponsorName",
    "StartDate",
    "CompletionDate",
    "LastUpdatePostDate",
]
DEFAULT_STUDY_FIELDS = [
    "IdentificationModule",
    "StatusModule",
    "SponsorCollaboratorsModule",
    "ConditionsModule",
    "DesignModule",
    "ArmsInterventionsModule",
    "OutcomesModule",
    "EligibilityModule",
]

mcp = MCPServer(
    "ClinicalTrials.gov",
    version=__version__,
    instructions=(
        "Read public study records from the official ClinicalTrials.gov API v2. Use "
        "clinicalgov_search_studies to discover NCT IDs and clinicalgov_get_study for details. "
        "Treat registry records as external reference data, preserve NCT IDs and update dates, and do not "
        "interpret study registration as evidence of safety, efficacy, or regulatory approval."
    ),
)


def _client() -> ClinicalTrialsGovClient:
    return ClinicalTrialsGovClient.from_settings()


async def _get(
    endpoint: str,
    *,
    params: dict[str, str | int | float | bool] | None = None,
) -> dict[str, Any] | list[Any]:
    return await _client().get(endpoint, params=params)


async def _get_object(
    endpoint: str,
    *,
    params: dict[str, str | int | float | bool] | None = None,
) -> dict[str, Any]:
    value = await _get(endpoint, params=params)
    if not isinstance(value, dict):
        raise ValueError("ClinicalTrials.gov returned an unexpected non-object response")
    return value


def _clean_optional(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > 500:
        raise ValueError(f"{label} must be 500 characters or fewer")
    return cleaned or None


def _fields(value: list[str] | None, default: list[str]) -> str:
    selected = value or default
    if not 1 <= len(selected) <= 40:
        raise ValueError("fields must contain between 1 and 40 field or module names")
    cleaned: list[str] = []
    for field in selected:
        candidate = field.strip()
        if not candidate or not candidate.replace("_", "").isalnum():
            raise ValueError("each field must be a ClinicalTrials.gov field or module name")
        cleaned.append(candidate)
    return ",".join(cleaned)


@mcp.tool()
async def clinicalgov_status(check_remote: bool = False) -> dict[str, Any]:
    """Show non-secret service configuration and optionally read API/data version details."""

    settings = get_settings()
    result: dict[str, Any] = {"api_base_url": settings.clinicalgov_api_base_url}
    if check_remote:
        result["remote"] = await _get_object("/version")
    return result


@mcp.tool()
async def clinicalgov_search_studies(
    query: str | None = None,
    condition: str | None = None,
    intervention: str | None = None,
    sponsor: str | None = None,
    location: str | None = None,
    overall_status: list[OverallStatus] | None = None,
    fields: list[str] | None = None,
    page_size: int = 10,
    page_token: str | None = None,
    sort: str | None = None,
    count_total: bool = True,
) -> dict[str, Any]:
    """Search current ClinicalTrials.gov records with bounded results; use nextPageToken to continue."""

    if not 1 <= page_size <= 25:
        raise ValueError("page_size must be between 1 and 25")
    params: dict[str, str | int | bool] = {
        "format": "json",
        "pageSize": page_size,
        "countTotal": count_total,
        "fields": _fields(fields, DEFAULT_SEARCH_FIELDS),
    }
    for api_name, value, label in (
        ("query.term", query, "query"),
        ("query.cond", condition, "condition"),
        ("query.intr", intervention, "intervention"),
        ("query.spons", sponsor, "sponsor"),
        ("query.locn", location, "location"),
        ("sort", sort, "sort"),
    ):
        cleaned = _clean_optional(value, label)
        if cleaned:
            params[api_name] = cleaned
    if overall_status:
        params["filter.overallStatus"] = ",".join(overall_status)
    if page_token:
        if len(page_token) > 1000:
            raise ValueError("page_token is too long")
        params["pageToken"] = page_token
    return await _get_object("/studies", params=params)


@mcp.tool()
async def clinicalgov_get_study(
    nct_id: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Get one current study record by NCT ID, optionally selecting up to 40 fields or modules."""

    normalized = ClinicalTrialsGovClient.normalize_nct_id(nct_id)
    return await _get_object(
        f"/studies/{normalized}",
        params={"format": "json", "fields": _fields(fields, DEFAULT_STUDY_FIELDS)},
    )


@mcp.tool()
async def clinicalgov_get_api_info() -> dict[str, Any]:
    """Get the API version, source-data timestamp, and current study-size statistics."""

    return {
        "version": await _get_object("/version"),
        "study_stats": await _get_object("/stats/size"),
    }


@mcp.tool()
async def clinicalgov_read_endpoint(
    endpoint: str,
    query: dict[str, str | int | float | bool] | None = None,
) -> dict[str, Any] | list[Any]:
    """Read an allowed relative API v2 endpoint; absolute URLs, query strings, and writes are rejected."""

    return await _get(endpoint, params=query)


def _arguments() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the standalone ClinicalTrials.gov MCP service.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=settings.clinicalgov_mcp_transport,
    )
    parser.add_argument("--host", default=settings.clinicalgov_mcp_host)
    parser.add_argument("--port", type=int, default=settings.clinicalgov_mcp_port)
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
