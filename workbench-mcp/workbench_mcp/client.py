from __future__ import annotations

import json
from typing import Any

import httpx

from .config import get_settings


class WorkbenchClient:
    def __init__(self, *, base_url: str, timeout: float = 60.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "WorkbenchClient":
        settings = get_settings()
        return cls(base_url=settings.workbench_api_url, timeout=settings.workbench_api_timeout_seconds)

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text or f"HTTP {response.status_code}"}
        if response.is_error:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            raise RuntimeError(f"Workbench API rejected the request ({response.status_code}): {detail}")
        return payload

    async def submit_text_job(
        self,
        use_case: str,
        *,
        inputs: list[dict[str, str]],
        options: dict[str, Any],
        acknowledged: bool,
    ) -> dict[str, Any]:
        data = {"options": json.dumps({**options, "deidentified_acknowledged": acknowledged})}
        files = [
            ("files", (item["filename"], item["content"].encode("utf-8"), "text/plain"))
            for item in inputs
        ]
        return await self.request("POST", f"/jobs/{use_case}", data=data, files=files)
