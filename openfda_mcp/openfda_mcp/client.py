"""Validated asynchronous client for the public openFDA API."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any

import httpx

from .catalog import ENDPOINTS
from .config import Settings

BASE_URL = "https://api.fda.gov"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
FIELD_RE = re.compile(r"^[A-Za-z0-9_.]+$")
SORT_RE = re.compile(r"^[A-Za-z0-9_.]+:(?:asc|desc)$", re.IGNORECASE)


class OpenFDAError(RuntimeError):
    """An expected error returned by openFDA or caused by an invalid query."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenFDAClient:
    """Small openFDA client with endpoint allowlisting, retry, and key redaction."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self._http_client = http_client

    @staticmethod
    def normalize_endpoint(endpoint: str) -> str:
        normalized = endpoint.strip().lower().lstrip("/")
        if normalized.endswith(".json"):
            normalized = normalized[:-5]
        if normalized not in ENDPOINTS:
            supported = ", ".join(sorted(ENDPOINTS))
            raise OpenFDAError(
                f"Unsupported endpoint '{endpoint}'. Use one of: {supported}."
            )
        return normalized

    def validate_limit(self, limit: int) -> None:
        if not 1 <= limit <= self.settings.max_results:
            raise OpenFDAError(
                f"limit must be between 1 and {self.settings.max_results} "
                "(controlled by OPENFDA_MAX_RESULTS)."
            )

    @staticmethod
    def validate_field(field: str) -> str:
        normalized = field.strip()
        if not normalized or not FIELD_RE.fullmatch(normalized):
            raise OpenFDAError(
                f"Invalid field '{field}'. Field names may contain letters, numbers, "
                "dots, and underscores."
            )
        return normalized

    async def query(
        self,
        endpoint: str,
        *,
        search: str | None = None,
        sort: str | None = None,
        limit: int = 10,
        skip: int = 0,
        count: str | None = None,
    ) -> dict[str, Any]:
        endpoint = self.normalize_endpoint(endpoint)
        self.validate_limit(limit)
        if not 0 <= skip <= 25_000:
            raise OpenFDAError("skip must be between 0 and 25000.")
        if search is not None:
            search = search.strip()
            if not search:
                search = None
            elif len(search) > 2048:
                raise OpenFDAError("search cannot exceed 2048 characters.")
        if sort is not None:
            sort = sort.strip()
            if not SORT_RE.fullmatch(sort):
                raise OpenFDAError("sort must use the form field:asc or field:desc.")
        if count is not None:
            count = self.validate_field(count)

        params: dict[str, str | int] = {}
        if search:
            params["search"] = search
        if sort:
            params["sort"] = sort
        if count:
            params["count"] = count
            params["limit"] = limit
        else:
            params["limit"] = limit
            if skip:
                params["skip"] = skip

        response = await self._request(f"/{endpoint}.json", params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenFDAError("openFDA returned an invalid JSON response.") from exc
        if not isinstance(payload, dict):
            raise OpenFDAError("openFDA returned an unexpected response shape.")

        payload["source"] = {
            "dataset": endpoint,
            "url": str(response.request.url.copy_remove_param("api_key")),
            "retrieved_from": "openFDA",
        }
        return payload

    async def _request(
        self, path: str, params: Mapping[str, str | int]
    ) -> httpx.Response:
        if self._http_client is not None:
            return await self._request_with_client(self._http_client, path, params)

        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=self.settings.timeout_seconds,
            headers={"User-Agent": self.settings.user_agent, "Accept": "application/json"},
        ) as client:
            return await self._request_with_client(client, path, params)

    async def _request_with_client(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: Mapping[str, str | int],
    ) -> httpx.Response:
        response: httpx.Response | None = None
        auth = (
            httpx.BasicAuth(self.settings.api_key, "")
            if self.settings.api_key
            else None
        )
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await client.get(path, params=params, auth=auth)
            except httpx.TimeoutException as exc:
                if attempt >= self.settings.max_retries:
                    raise OpenFDAError("The openFDA request timed out; retry later.") from exc
                await asyncio.sleep(0.25 * (2**attempt))
                continue
            except httpx.RequestError as exc:
                if attempt >= self.settings.max_retries:
                    raise OpenFDAError(
                        f"Could not reach openFDA: {exc.__class__.__name__}."
                    ) from exc
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            if response.status_code not in RETRYABLE_STATUS_CODES:
                break
            if attempt >= self.settings.max_retries:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                delay = (
                    max(0.0, min(float(retry_after), 2.0))
                    if retry_after
                    else 0.25 * (2**attempt)
                )
            except ValueError:
                delay = 0.25 * (2**attempt)
            await asyncio.sleep(delay)

        assert response is not None
        if response.is_success:
            return response
        raise self._to_error(response)

    @staticmethod
    def _to_error(response: httpx.Response) -> OpenFDAError:
        message = "The openFDA request failed."
        try:
            body = response.json()
            api_error = body.get("error", {}) if isinstance(body, dict) else {}
            detail = api_error.get("message") if isinstance(api_error, dict) else None
            if detail:
                message = str(detail)
        except ValueError:
            pass

        if response.status_code == 404:
            message = f"No openFDA records matched the query. {message}"
        elif response.status_code == 429:
            message = "openFDA rate limit exceeded. Add an API key or retry later."
        elif response.status_code == 400:
            message = f"openFDA rejected the query: {message}"
        elif response.status_code >= 500:
            message = "openFDA is temporarily unavailable; retry later."
        return OpenFDAError(message, status_code=response.status_code)


def exact_search(field: str, value: str) -> str:
    """Build a quoted exact-value query without allowing query injection."""
    normalized_field = OpenFDAClient.validate_field(field)
    normalized_value = value.strip()
    if not normalized_value:
        raise OpenFDAError("value cannot be empty.")
    if len(normalized_value) > 500:
        raise OpenFDAError("value cannot exceed 500 characters.")
    escaped_value = normalized_value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{normalized_field}:"{escaped_value}"'


def project_records(payload: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """Project records to requested dotted paths while preserving response metadata."""
    if not fields:
        return payload
    if len(fields) > 25:
        raise OpenFDAError("At most 25 fields can be selected.")
    normalized_fields = [OpenFDAClient.validate_field(field) for field in fields]
    results = payload.get("results")
    if not isinstance(results, list):
        return payload

    projected: list[dict[str, Any]] = []
    for record in results:
        if not isinstance(record, dict):
            continue
        selected: dict[str, Any] = {}
        for field in normalized_fields:
            found, value = _extract_path(record, field.split("."))
            if found:
                selected[field] = value
        projected.append(selected)
    return {**payload, "results": projected, "selected_fields": normalized_fields}


def _extract_path(value: Any, parts: list[str]) -> tuple[bool, Any]:
    if not parts:
        return True, value
    if isinstance(value, dict):
        key = parts[0]
        if key not in value:
            return False, None
        return _extract_path(value[key], parts[1:])
    if isinstance(value, list):
        extracted = [_extract_path(item, parts) for item in value]
        present = [item for found, item in extracted if found]
        return (bool(present), present)
    return False, None

