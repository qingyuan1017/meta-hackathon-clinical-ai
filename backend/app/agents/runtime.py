from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import Client as MCPClient
from pydantic import BaseModel, ValidationError

from ..ai import AIResponseError, MetaAIClient
from ..config import Settings
from ..parsers import chunk_text
from .definitions import (
    BIOPORTAL_TOOLS,
    CDISC_TOOLS,
    CLINICALGOV_TOOLS,
    OPENFDA_TOOLS,
    PUBMED_TOOLS,
    AgentDefinition,
)


@dataclass
class AgentOutcome:
    value: BaseModel
    warnings: list[str]


class ClinicalAgentRunner:
    """Bounded one-tool-per-turn agent loop backed by the Meta Model API."""

    def __init__(
        self,
        *,
        definition: AgentDefinition,
        result_model: type[BaseModel],
        ai: MetaAIClient,
        settings: Settings,
        progress_path: Path | None = None,
    ) -> None:
        self.definition = definition
        self.result_model = result_model
        self.ai = ai
        self.settings = settings
        self.progress_path = progress_path

    async def run(self, *, objective: str, source: str, options: dict[str, Any]) -> AgentOutcome:
        all_chunks = chunk_text(source, self.settings.chunk_characters)
        chunks = all_chunks[: self.settings.max_source_chunks]
        warnings: list[str] = []
        if len(all_chunks) > len(chunks):
            warnings.append(
                f"Source was limited to the first {len(chunks)} of {len(all_chunks)} extracted chunks."
            )
        state: dict[str, Any] = {
            "contract_inspected": False,
            "read_chunks": set(),
            "remote_calls": 0,
            "submitted": None,
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.definition.instructions()},
            {
                "role": "user",
                "content": (
                    f"OBJECTIVE\n{objective}\n\nOPTIONS\n{json.dumps(options, ensure_ascii=False)}\n\n"
                    f"SOURCE INVENTORY\n{len(chunks)} chunk(s) are available through read_source_chunk."
                ),
            }
        ]
        trace: dict[str, Any] = {
            "agent_id": self.definition.id,
            "workflow": self.definition.workflow,
            "model": self.settings.meta_model,
            "status": "running",
            "turn": 0,
            "max_turns": self.settings.agent_max_turns,
            "total_source_chunks": len(chunks),
            "read_source_chunks": [],
            "started_at": self._now(),
            "updated_at": self._now(),
            "messages": messages,
            "events": [],
        }
        self._save_trace(trace)

        async with AsyncExitStack() as stack:
            remote_definitions, remote_clients, connection_warnings = await self._connect_remote_tools(stack)
            warnings.extend(connection_warnings)
            tools = [*self._internal_tool_definitions(len(chunks)), *remote_definitions]
            for turn in range(1, self.settings.agent_max_turns + 1):
                if turn == self.settings.agent_max_turns:
                    messages.append(
                        {
                            "role": "user",
                            "content": "This is the final turn. Call submit_result with the best supportable draft now.",
                        }
                    )
                try:
                    response = await self.ai.client.chat.completions.create(
                        model=self.settings.meta_model,
                        messages=messages,
                        temperature=0.1,
                        tools=tools,
                        tool_choice="auto",
                        parallel_tool_calls=False,
                    )
                except Exception as exc:
                    trace["status"] = "paused"
                    trace["updated_at"] = self._now()
                    trace["error"] = f"Model API call failed: {str(exc)[:500]}"
                    self._save_trace(trace)
                    raise
                message = response.choices[0].message
                assistant = message.model_dump(exclude_none=True)
                messages.append(assistant)
                trace["turn"] = turn
                trace["messages"] = messages

                calls = list(message.tool_calls or [])
                if not calls:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Plain text is not accepted. Call exactly one available tool.",
                        }
                    )
                    trace["events"].append({"turn": turn, "type": "plain_text_rejected"})
                    trace["updated_at"] = self._now()
                    self._save_trace(trace)
                    continue
                if len(calls) != 1:
                    for call in calls:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(
                                    {"ok": False, "error": "Call exactly one tool per turn."}
                                ),
                            }
                        )
                    trace["events"].append(
                        {"turn": turn, "type": "multiple_tools_rejected", "count": len(calls)}
                    )
                    trace["updated_at"] = self._now()
                    self._save_trace(trace)
                    continue

                call = calls[0]
                arguments, argument_error = self._arguments(call.function.arguments)
                if argument_error:
                    result = {"ok": False, "error": argument_error}
                elif call.function.name in {
                    "inspect_workflow_contract",
                    "read_source_chunk",
                    "submit_result",
                }:
                    result = self._run_internal_tool(
                        call.function.name,
                        arguments,
                        chunks=chunks,
                        options=options,
                        state=state,
                    )
                else:
                    result = await self._run_remote_tool(call, remote_clients, state)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
                trace["messages"] = messages
                trace["read_source_chunks"] = sorted(state["read_chunks"])
                trace["events"].append(
                    {
                        "turn": turn,
                        "type": "tool",
                        "name": call.function.name,
                        "ok": bool(result.get("ok")),
                        "error": result.get("error"),
                    }
                )
                trace["updated_at"] = self._now()
                if state["submitted"] is not None:
                    trace["status"] = "completed"
                    trace["completed_at"] = self._now()
                    self._save_trace(trace)
                    return AgentOutcome(value=state["submitted"], warnings=warnings)
                self._save_trace(trace)

        trace["status"] = "paused"
        trace["updated_at"] = self._now()
        trace["error"] = "turn_limit"
        self._save_trace(trace)
        raise AIResponseError(
            f"{self.definition.name} reached the {self.settings.agent_max_turns}-turn limit without a valid result."
        )

    def _internal_tool_definitions(self, chunk_count: int) -> list[dict[str, Any]]:
        result_schema = self.result_model.model_json_schema()
        definitions = result_schema.pop("$defs", None)
        submission_parameters: dict[str, Any] = {
            "type": "object",
            "properties": {"result": result_schema},
            "required": ["result"],
            "additionalProperties": False,
        }
        if definitions:
            submission_parameters["$defs"] = definitions
        return [
            {
                "type": "function",
                "function": {
                    "name": "inspect_workflow_contract",
                    "description": "Read the workflow contract and exact structured result schema before investigating.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_source_chunk",
                    "description": "Read one extracted source chunk. Every available chunk must be read before submission.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "index": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": max(chunk_count, 1),
                            }
                        },
                        "required": ["index"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_result",
                    "description": "Submit the complete draft. The backend validates its schema and cross-references.",
                    "parameters": submission_parameters,
                },
            },
        ]

    def _run_internal_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        chunks: list[str],
        options: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "inspect_workflow_contract":
            state["contract_inspected"] = True
            return {
                "ok": True,
                "agent": self.definition.id,
                "workflow": self.definition.workflow,
                "options": options,
                "source_chunks": len(chunks),
                "result_schema": self.result_model.model_json_schema(),
                "submission_rules": [
                    "Read every source chunk.",
                    "Preserve uncertainty and missing information.",
                    "Submit only facts supported by the supplied source or clearly attributed public references.",
                ],
            }
        if not state["contract_inspected"]:
            return {"ok": False, "error": "Inspect the workflow contract first."}
        if name == "read_source_chunk":
            index = arguments.get("index")
            if not isinstance(index, int) or index < 1 or index > len(chunks):
                return {"ok": False, "error": f"index must be between 1 and {len(chunks)}"}
            state["read_chunks"].add(index)
            return {
                "ok": True,
                "index": index,
                "total": len(chunks),
                "content": chunks[index - 1],
            }
        if name == "submit_result":
            unread = sorted(set(range(1, len(chunks) + 1)) - state["read_chunks"])
            if unread:
                return {"ok": False, "error": "Read every source chunk before submission.", "unread": unread}
            raw = arguments.get("result")
            if not isinstance(raw, dict):
                return {"ok": False, "error": "result must be a JSON object"}
            try:
                validated = self.result_model.model_validate(raw)
            except ValidationError as exc:
                return {
                    "ok": False,
                    "error": "Result schema validation failed.",
                    "problems": exc.errors(include_url=False),
                }
            problems = verify_result(self.definition.workflow, validated)
            if problems:
                return {"ok": False, "error": "Result verification failed.", "problems": problems}
            state["submitted"] = validated
            return {"ok": True, "accepted": True, "status": "completed"}
        return {"ok": False, "error": f"Unknown internal tool: {name}"}

    async def _connect_remote_tools(
        self, stack: AsyncExitStack
    ) -> tuple[list[dict[str, Any]], dict[str, MCPClient], list[str]]:
        definitions: list[dict[str, Any]] = []
        clients: dict[str, MCPClient] = {}
        warnings: list[str] = []
        allowed = set(self.definition.remote_tools)
        for label, enabled, url, server_tools in self._server_specs():
            if not enabled or not allowed.intersection(server_tools):
                continue
            try:
                client = await stack.enter_async_context(MCPClient(url))
                listed = await client.list_tools()
            except Exception as exc:
                warnings.append(f"Optional {label} MCP tools were unavailable: {str(exc)[:240]}")
                continue
            for tool in listed.tools:
                if tool.name not in allowed:
                    continue
                if tool.name in clients:
                    raise AIResponseError(f"Duplicate agent tool name: {tool.name}")
                clients[tool.name] = client
                definitions.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.input_schema,
                        },
                    }
                )
        return definitions, clients, warnings

    async def _run_remote_tool(
        self, call: Any, clients: dict[str, MCPClient], state: dict[str, Any]
    ) -> dict[str, Any]:
        if not state["contract_inspected"]:
            return {"ok": False, "error": "Inspect the workflow contract first."}
        client = clients.get(call.function.name)
        if client is None:
            return {"ok": False, "error": "This external tool is not available."}
        if state["remote_calls"] >= self.settings.agent_max_remote_tool_calls:
            return {"ok": False, "error": "The external-tool call limit has been reached."}
        state["remote_calls"] += 1
        try:
            raw = await MetaAIClient._call_mcp_tool(clients, call)
        except Exception as exc:
            return {"ok": False, "error": f"External tool failed: {str(exc)[:500]}"}
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"ok": True, "result": payload}

    def _server_specs(self) -> list[tuple[str, bool, str, tuple[str, ...]]]:
        return [
            ("CDISC Library", self.settings.cdisc_mcp_enabled, self.settings.cdisc_mcp_url, CDISC_TOOLS),
            (
                "ClinicalTrials.gov",
                self.settings.clinicalgov_mcp_enabled,
                self.settings.clinicalgov_mcp_url,
                CLINICALGOV_TOOLS,
            ),
            ("openFDA", self.settings.openfda_mcp_enabled, self.settings.openfda_mcp_url, OPENFDA_TOOLS),
            ("BioPortal", self.settings.bioportal_mcp_enabled, self.settings.bioportal_mcp_url, BIOPORTAL_TOOLS),
            ("PubMed", self.settings.pubmed_mcp_enabled, self.settings.pubmed_mcp_url, PUBMED_TOOLS),
        ]

    @staticmethod
    def _arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            return {}, f"Invalid tool arguments: {exc}"
        if not isinstance(value, dict):
            return {}, "Tool arguments must be a JSON object."
        return value, None

    def _save_trace(self, trace: dict[str, Any]) -> None:
        if self.progress_path is None:
            return
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.progress_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(trace, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        temporary.replace(self.progress_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def verify_result(workflow: str, value: BaseModel) -> list[str]:
    """Deterministic cross-reference checks that the model cannot bypass."""

    problems: list[str] = []
    if workflow == "clinical-document":
        headings = [section.heading.strip().casefold() for section in value.sections]
        if len(headings) != len(set(headings)):
            problems.append("Document section headings must be unique.")
    elif workflow == "edc-design":
        form_ids = [form.form_id for form in value.forms]
        if len(form_ids) != len(set(form_ids)):
            problems.append("EDC form_id values must be unique.")
        known_forms = {form.form_id: {field.field_id for field in form.fields} for form in value.forms}
        known_codelists = {item.name for item in value.codelists}
        for visit in value.visits:
            for form_id in visit.forms:
                if form_id not in known_forms:
                    problems.append(f"Visit {visit.name} references unknown form {form_id}.")
        for form in value.forms:
            field_ids = [field.field_id for field in form.fields]
            if len(field_ids) != len(set(field_ids)):
                problems.append(f"Form {form.form_id} has duplicate field_id values.")
            for field in form.fields:
                if field.codelist and field.codelist not in known_codelists:
                    problems.append(f"Field {form.form_id}.{field.field_id} references unknown codelist {field.codelist}.")
        for check in value.edit_checks:
            if check.form not in known_forms:
                problems.append(f"Edit check {check.check_id} references unknown form {check.form}.")
            elif check.field not in known_forms[check.form]:
                problems.append(f"Edit check {check.check_id} references unknown field {check.form}.{check.field}.")
    elif workflow == "sdtm":
        domains = [dataset.domain.upper() for dataset in value.datasets]
        if len(domains) != len(set(domains)):
            problems.append("SDTM domain identifiers must be unique.")
        for dataset in value.datasets:
            variables = [variable.name.upper() for variable in dataset.variables]
            if len(variables) != len(set(variables)):
                problems.append(f"Domain {dataset.domain} has duplicate variable names.")
        if "3.4" not in value.standard:
            problems.append("The draft must identify SDTMIG 3.4 as its baseline.")
        if "2.1" not in value.define_standard:
            problems.append("The draft must identify Define-XML 2.1 as its baseline.")
    elif workflow == "tlf":
        output_ids = [item.output_id for item in value.outputs]
        if len(output_ids) != len(set(output_ids)):
            problems.append("TLF output_id values must be unique.")
    return list(dict.fromkeys(problems))
