from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from .config import Settings, get_settings


RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}
ALLOWED_EXACT_PATHS = {"/annotator", "/ontologies", "/recommender", "/search"}


class BioPortalError(RuntimeError):
    """A safe, user-facing error returned by the BioPortal client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BioPortalConfigurationError(BioPortalError):
    """Raised when the BioPortal client is not configured."""


class BioPortalClient:
    """Small async client for the read-only NCBO BioPortal API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://data.bioontology.org",
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise BioPortalConfigurationError(
                "BioPortal is not configured. Set BIOPORTAL_API_KEY in the environment."
            )
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> BioPortalClient:
        configured = settings or get_settings()
        return cls(
            configured.bioportal_api_key,
            base_url=configured.bioportal_api_base_url,
            timeout_seconds=configured.bioportal_api_timeout_seconds,
        )

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int | float | bool] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Fetch one allowed BioPortal endpoint and decode its JSON/JSON-LD response."""

        path = self.validate_endpoint(endpoint)
        headers = {
            "Accept": "application/json",
            "Authorization": f"apikey token={self._api_key}",
            "User-Agent": "clinical-ai-bioportal-mcp/0.1",
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            response: httpx.Response | None = None
            for attempt in range(3):
                try:
                    response = await client.get(path, params=params)
                except httpx.RequestError as exc:
                    if attempt == 2:
                        raise BioPortalError(
                            "Could not reach the BioPortal API. Check the base URL, network, and proxy settings."
                        ) from exc
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt == 2:
                    break
                await asyncio.sleep(0.25 * (2**attempt))

        if response is None:  # pragma: no cover - defensive
            raise BioPortalError("The BioPortal request did not return a response.")
        if response.is_error:
            raise self._response_error(response)
        try:
            value = response.json()
        except ValueError as exc:
            raise BioPortalError(
                "BioPortal returned a non-JSON response.", status_code=response.status_code
            ) from exc
        if not isinstance(value, (dict, list)):
            raise BioPortalError(
                "BioPortal returned an unexpected JSON value.", status_code=response.status_code
            )
        return value

    @staticmethod
    def validate_endpoint(endpoint: str) -> str:
        """Allow only relative paths used by the focused, read-only BioPortal tools."""

        candidate = endpoint.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("endpoint must be a relative API path without a query string or fragment")
        path = "/" + candidate.lstrip("/")
        decoded_path = unquote(path)
        if ".." in decoded_path.split("/"):
            raise ValueError("endpoint may not contain path traversal segments")
        if path in ALLOWED_EXACT_PATHS or path.startswith("/ontologies/"):
            return path
        raise ValueError("endpoint is not part of the allowed BioPortal read surface")

    def _response_error(self, response: httpx.Response) -> BioPortalError:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("detail") or body.get("error") or "")
        except ValueError:
            detail = response.text.strip()
        detail = " ".join(detail.split()).replace(self._api_key, "[REDACTED]")[:500]
        if response.status_code in {401, 403}:
            message = "BioPortal rejected the API key or access to this resource."
        elif response.status_code == 404:
            message = "The requested BioPortal ontology or class was not found."
        elif response.status_code == 429:
            message = "BioPortal rate limit exceeded. Retry later."
        else:
            message = f"BioPortal returned HTTP {response.status_code}."
        if detail:
            message = f"{message} {detail}"
        return BioPortalError(message, status_code=response.status_code)
