from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from .config import Settings, get_settings


RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}
ALLOWED_API_PREFIXES = ("/mdr/", "/cosmos/")


class CDISCLibraryError(RuntimeError):
    """A safe, user-facing error returned by the CDISC Library client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CDISCConfigurationError(CDISCLibraryError):
    """Raised when the CDISC Library client is not configured."""


class CDISCLibraryClient:
    """Small async client for the read-only CDISC Library REST API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://library.cdisc.org/api",
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise CDISCConfigurationError(
                "CDISC Library is not configured. Set CDISC_LIBRARY_API_KEY in the environment."
            )
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> CDISCLibraryClient:
        configured = settings or get_settings()
        return cls(
            configured.cdisc_library_api_key,
            base_url=configured.cdisc_library_base_url,
            timeout_seconds=configured.cdisc_library_timeout_seconds,
        )

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int | float | bool] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Fetch one allowed CDISC Library endpoint and decode its JSON response."""

        path = self.validate_endpoint(endpoint)
        headers = {
            "Accept": "application/json",
            "api-key": self._api_key,
            "User-Agent": "clinical-ai-cdisc-mcp/0.1",
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
                        raise CDISCLibraryError(
                            "Could not reach the CDISC Library API. Check the base URL, network, and proxy settings."
                        ) from exc
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt == 2:
                    break
                await asyncio.sleep(0.25 * (2**attempt))

        if response is None:  # pragma: no cover - defensive; the loop always sets or raises
            raise CDISCLibraryError("The CDISC Library request did not return a response.")
        if response.is_error:
            raise self._response_error(response)
        try:
            value = response.json()
        except ValueError as exc:
            raise CDISCLibraryError(
                "The CDISC Library returned a non-JSON response.", status_code=response.status_code
            ) from exc
        if not isinstance(value, (dict, list)):
            raise CDISCLibraryError(
                "The CDISC Library returned an unexpected JSON value.", status_code=response.status_code
            )
        return value

    @staticmethod
    def validate_endpoint(endpoint: str) -> str:
        """Allow only relative, read-only CDISC Library paths."""

        candidate = endpoint.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("endpoint must be a relative API path without a query string or fragment")
        path = "/" + candidate.lstrip("/")
        decoded_path = unquote(path)
        if ".." in decoded_path.split("/"):
            raise ValueError("endpoint may not contain path traversal segments")
        if path == "/health" or path.startswith(ALLOWED_API_PREFIXES):
            return path
        raise ValueError("endpoint must be /health, /mdr/..., or /cosmos/...")

    def _response_error(self, response: httpx.Response) -> CDISCLibraryError:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("detail") or body.get("error") or "")
        except ValueError:
            detail = response.text.strip()
        detail = " ".join(detail.split()).replace(self._api_key, "[REDACTED]")[:500]
        if response.status_code in {401, 403}:
            message = "CDISC Library rejected the API key or the account does not have access to this resource."
        elif response.status_code == 404:
            message = "The requested CDISC Library resource was not found. Use product links for valid identifiers."
        elif response.status_code == 429:
            message = "CDISC Library rate limit exceeded. Retry later."
        else:
            message = f"CDISC Library returned HTTP {response.status_code}."
        if detail:
            message = f"{message} {detail}"
        return CDISCLibraryError(message, status_code=response.status_code)
