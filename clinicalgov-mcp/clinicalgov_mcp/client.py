from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from .config import Settings, get_settings


RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}
NCT_ID = re.compile(r"NCT\d{8}", re.IGNORECASE)
ALLOWED_EXACT_PATHS = {
    "/studies",
    "/studies/metadata",
    "/studies/search-areas",
    "/studies/enums",
    "/stats/size",
    "/stats/field/values",
    "/stats/field/sizes",
    "/version",
}


class ClinicalTrialsGovError(RuntimeError):
    """A safe, user-facing error returned by the ClinicalTrials.gov client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ClinicalTrialsGovClient:
    """Small async client for the read-only ClinicalTrials.gov API v2."""

    def __init__(
        self,
        *,
        base_url: str = "https://clinicaltrials.gov/api/v2",
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ClinicalTrialsGovClient:
        configured = settings or get_settings()
        return cls(
            base_url=configured.clinicalgov_api_base_url,
            timeout_seconds=configured.clinicalgov_api_timeout_seconds,
        )

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int | float | bool] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Fetch one allowed API v2 endpoint and decode its JSON response."""

        path = self.validate_endpoint(endpoint)
        headers = {
            "Accept": "application/json",
            "User-Agent": "clinicalgov-mcp-service/0.1",
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
                        raise ClinicalTrialsGovError(
                            "Could not reach ClinicalTrials.gov. Check the base URL, network, and proxy settings."
                        ) from exc
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt == 2:
                    break
                await asyncio.sleep(0.25 * (2**attempt))

        if response is None:  # pragma: no cover
            raise ClinicalTrialsGovError("The ClinicalTrials.gov request did not return a response.")
        if response.is_error:
            raise self._response_error(response)
        try:
            value = response.json()
        except ValueError as exc:
            raise ClinicalTrialsGovError(
                "ClinicalTrials.gov returned a non-JSON response.", status_code=response.status_code
            ) from exc
        if not isinstance(value, (dict, list)):
            raise ClinicalTrialsGovError(
                "ClinicalTrials.gov returned an unexpected JSON value.", status_code=response.status_code
            )
        return value

    @staticmethod
    def normalize_nct_id(value: str) -> str:
        candidate = value.strip().upper()
        if not NCT_ID.fullmatch(candidate):
            raise ValueError("nct_id must use the format NCT followed by eight digits")
        return candidate

    @classmethod
    def validate_endpoint(cls, endpoint: str) -> str:
        """Allow only relative, read-only paths from the documented API v2 surface."""

        candidate = endpoint.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("endpoint must be a relative API path without a query string or fragment")
        path = "/" + candidate.lstrip("/")
        decoded_path = unquote(path)
        if ".." in decoded_path.split("/"):
            raise ValueError("endpoint may not contain path traversal segments")
        if path in ALLOWED_EXACT_PATHS:
            return path
        if path.startswith("/studies/"):
            cls.normalize_nct_id(path.removeprefix("/studies/"))
            return path
        raise ValueError("endpoint is not part of the allowed ClinicalTrials.gov API v2 read surface")

    @staticmethod
    def _response_error(response: httpx.Response) -> ClinicalTrialsGovError:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("detail") or body.get("error") or "")
        except ValueError:
            detail = response.text.strip()
        detail = " ".join(detail.split())[:500]
        if response.status_code == 404:
            message = "The requested ClinicalTrials.gov study or resource was not found."
        elif response.status_code == 429:
            message = "ClinicalTrials.gov rate limit exceeded. Retry later."
        else:
            message = f"ClinicalTrials.gov returned HTTP {response.status_code}."
        if detail:
            message = f"{message} {detail}"
        return ClinicalTrialsGovError(message, status_code=response.status_code)
