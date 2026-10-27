"""Environment-based server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _read_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str | None = None
    timeout_seconds: float = 30.0
    max_results: int = 100
    max_retries: int = 2
    user_agent: str = "openfda-mcp/0.1.0"

    @classmethod
    def from_env(cls) -> Settings:
        api_key = os.getenv("OPENFDA_API_KEY") or None
        user_agent = os.getenv("OPENFDA_USER_AGENT", "openfda-mcp/0.1.0").strip()
        if not user_agent:
            raise ValueError("OPENFDA_USER_AGENT cannot be empty")
        return cls(
            api_key=api_key,
            timeout_seconds=_read_float(
                "OPENFDA_TIMEOUT_SECONDS", 30.0, minimum=1.0, maximum=120.0
            ),
            max_results=_read_int("OPENFDA_MAX_RESULTS", 100, minimum=1, maximum=1000),
            max_retries=_read_int("OPENFDA_MAX_RETRIES", 2, minimum=0, maximum=5),
            user_agent=user_agent,
        )

