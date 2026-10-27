from __future__ import annotations

import json
import re
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings


T = TypeVar("T", bound=BaseModel)
JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.I | re.S)


class AIResponseError(RuntimeError):
    pass


class MetaAIClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.meta_api_key,
            base_url=self.settings.meta_api_base_url,
            timeout=self.settings.ai_timeout_seconds,
            max_retries=2,
        )

    async def generate_structured(
        self,
        *,
        schema: type[T],
        task: str,
        source: str,
        context: dict | None = None,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        context_json = json.dumps(context or {}, ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a clinical-research artifact drafting assistant. Work only from the supplied "
                    "synthetic or de-identified source. Never invent patient data. State uncertainty in the "
                    "schema's assumptions, ambiguities, or unresolved fields. Return only one JSON object "
                    "that conforms exactly to the supplied JSON Schema. Do not use markdown fences."
                ),
            },
            {
                "role": "user",
                "content": f"TASK\n{task}\n\nOPTIONS\n{context_json}\n\nJSON SCHEMA\n{schema_json}\n\nSOURCE\n{source}",
            },
        ]
        raw = await self._complete(messages)
        try:
            return schema.model_validate(self._decode_json(raw))
        except (json.JSONDecodeError, ValidationError, ValueError) as first_error:
            repair_messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "The previous response failed validation. Return a corrected JSON object only. "
                        f"Validation problem: {str(first_error)[:1800]}"
                    ),
                },
            ]
            repaired = await self._complete(repair_messages)
            try:
                return schema.model_validate(self._decode_json(repaired))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                raise AIResponseError(f"The model returned invalid structured data after one repair: {exc}") from exc

    async def _complete(self, messages: list[dict[str, str]]) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.meta_model,
            messages=messages,
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise AIResponseError("The model returned an empty response.")
        return content

    @staticmethod
    def _decode_json(raw: str) -> dict:
        candidate = raw.strip()
        fence = JSON_FENCE.search(candidate)
        if fence:
            candidate = fence.group(1).strip()
        first = candidate.find("{")
        last = candidate.rfind("}")
        if first >= 0 and last > first:
            candidate = candidate[first : last + 1]
        value = json.loads(candidate)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object.")
        return value
