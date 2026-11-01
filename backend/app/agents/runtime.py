from __future__ import annotations

import json
from time import perf_counter
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mcp import Client as MCPClient
from pydantic import BaseModel, ValidationError

from ..ai import AIResponseError, MetaAIClient
from ..config import Settings
from ..parsers import chunk_text
from ..sdtm_r import normalize_r_mapping_expression
from .base import AgentDefinition
from .tool_catalog import (
    BIOPORTAL_TOOLS,
    CDISC_TOOLS,
    CLINICALGOV_TOOLS,
    OPENFDA_TOOLS,
    PUBMED_TOOLS,
)


@dataclass
class AgentOutcome:
    value: BaseModel
    warnings: list[str]
    events: list[dict[str, Any]]


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
        result_validator: Callable[[BaseModel], None] | None = None,
        complete_source_chunk_limit: int | None = None,
    ) -> None:
        self.definition = definition
        self.result_model = result_model
        self.ai = ai
        self.settings = settings
        self.progress_path = progress_path
        self.result_validator = result_validator
        self.complete_source_chunk_limit = complete_source_chunk_limit

    async def run(
        self,
        *,
        objective: str,
        source: str,
        options: dict[str, Any],
        stage: str | None = None,
        stage_index: int = 1,
        stage_count: int = 1,
        completed_stages: list[str] | None = None,
        prior_events: list[dict[str, Any]] | None = None,
    ) -> AgentOutcome:
        saved_trace = self._load_trace()
        if prior_events is None and isinstance(saved_trace.get("events"), list):
            prior_events = [event for event in saved_trace["events"] if isinstance(event, dict)]
        preserved_events = list(prior_events or [])
        stage_turn_floor = (stage_index - 1) * self.settings.agent_max_turns
        prior_turns = [event.get("turn", 0) for event in preserved_events]
        base_turn = max([stage_turn_floor, *[int(value) for value in prior_turns if isinstance(value, int)]])

        all_chunks = chunk_text(source, self.settings.chunk_characters)
        configured_chunk_limit = (
            self.complete_source_chunk_limit
            if self.complete_source_chunk_limit is not None
            else self.settings.max_source_chunks
        )
        complete_read_limit = min(
            configured_chunk_limit,
            max(self.settings.agent_max_turns - 2, 1),
        )
        if len(all_chunks) > complete_read_limit:
            now = self._now()
            message = (
                f"Complete source requires {len(all_chunks)} chunks, exceeding the safe complete-read limit "
                f"of {complete_read_limit}. No partial source was sent to the model. Reduce or split the "
                "source with a workflow-specific complete-data strategy."
            )
            event = {
                "turn": base_turn + 1,
                "type": "source_capacity_exceeded",
                "actor": "system",
                "name": "complete_source_gate",
                "stage": stage,
                "ok": False,
                "error": message,
                "summary": "Stopped before model execution because the complete source could not be read safely.",
                "intent": "Prevent a draft from being generated from a truncated source prefix.",
                "input_summary": f"The complete source contains {len(all_chunks)} chunks.",
                "output_summary": "No source chunks were sent to the model and no draft was generated.",
                "input_details": {
                    "Complete source chunks": len(all_chunks),
                    "Complete-read limit": complete_read_limit,
                },
                "output_details": {
                    "Decision": "Fail closed",
                    "Partial model execution": False,
                },
                "evidence": ["Deterministic complete-source capacity check"],
                "occurred_at": now,
            }
            self._save_trace(
                {
                    "agent_id": self.definition.id,
                    "workflow": self.definition.workflow,
                    "model": self.settings.meta_model,
                    "status": "blocked",
                    "turn": base_turn + 1,
                    "max_turns": max(
                        self.settings.agent_max_turns * stage_count,
                        base_turn + self.settings.agent_max_turns,
                    ),
                    "stage": stage,
                    "stage_index": stage_index,
                    "stage_count": stage_count,
                    "completed_stages": list(completed_stages or []),
                    "total_source_chunks": len(all_chunks),
                    "read_source_chunks": [],
                    "started_at": now,
                    "updated_at": now,
                    "error": message,
                    "messages": [],
                    "events": [*preserved_events, event],
                }
            )
            raise AIResponseError(message)
        chunks = all_chunks
        warnings: list[str] = []
        state: dict[str, Any] = {
            "contract_inspected": False,
            "read_chunks": set(),
            "remote_calls": 0,
            "submitted": None,
        }
        prompt_options = {
            key: value
            for key, value in options.items()
            if key not in {"review_feedback", "_review_revision_result"}
        }
        review_entries = options.get("review_feedback")
        current_feedback = [
            item
            for item in review_entries
            if isinstance(item, dict)
            and (not stage or _review_stage_matches(str(item.get("stage", "")), stage))
            and str(item.get("message", "")).strip()
        ] if isinstance(review_entries, list) else []
        feedback_section = ""
        if current_feedback:
            guidance = "\n".join(
                f"{index}. {str(item['message']).strip()}\n"
                f"   Confirmed scope: {json.dumps(item.get('scope', {}), ensure_ascii=False)}"
                for index, item in enumerate(current_feedback, start=1)
            )
            baseline = options.get("_review_revision_result")
            baseline_text = json.dumps(baseline, ensure_ascii=False) if baseline is not None else "Not available"
            feedback_section = (
                "\n\nHUMAN REVIEW GUIDANCE\n"
                f"{guidance}\n\nCURRENT DRAFT TO REVISE\n{baseline_text}\n\n"
                "Apply the guidance in order; newer guidance overrides older conflicting guidance. "
                "Treat it as a user decision, not as source evidence. Change only the confirmed scope; "
                "the server will discard and audit every out-of-scope difference. Preserve source traceability "
                "and leave unsupported requests explicit rather than inventing facts."
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.definition.instructions()},
            {
                "role": "user",
                "content": (
                    f"OBJECTIVE\n{objective}\n\nOPTIONS\n{json.dumps(prompt_options, ensure_ascii=False)}\n\n"
                    f"SOURCE INVENTORY\n{len(chunks)} chunk(s) are available through read_source_chunk."
                    f"{feedback_section}"
                ),
            }
        ]
        trace: dict[str, Any] = {
            "agent_id": self.definition.id,
            "workflow": self.definition.workflow,
            "model": self.settings.meta_model,
            "status": "running",
            "turn": base_turn,
            "max_turns": max(self.settings.agent_max_turns * stage_count, base_turn + self.settings.agent_max_turns),
            "stage": stage,
            "stage_index": stage_index,
            "stage_count": stage_count,
            "completed_stages": list(completed_stages or []),
            "total_source_chunks": len(chunks),
            "read_source_chunks": [],
            "started_at": self._now(),
            "updated_at": self._now(),
            "messages": messages,
            "events": preserved_events,
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
                trace["turn"] = base_turn + turn
                trace["messages"] = messages

                calls = list(message.tool_calls or [])
                if not calls:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Plain text is not accepted. Call exactly one available tool.",
                        }
                    )
                    trace["events"].append(
                        {
                            "turn": trace["turn"],
                            "type": "plain_text_rejected",
                            "stage": stage,
                            "summary": "The agent responded without using a required tool, so the turn was rejected.",
                            "intent": "Continue the workflow with one auditable, approved action.",
                            "input_summary": "No tool request was received.",
                            "output_summary": "The agent was instructed to retry with exactly one approved tool.",
                            "input_details": {"Tool requests": 0},
                            "output_details": {"Policy": "Exactly one approved tool is required per turn."},
                            "evidence": [],
                            "occurred_at": self._now(),
                        }
                    )
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
                        {
                            "turn": trace["turn"],
                            "type": "multiple_tools_rejected",
                            "count": len(calls),
                            "stage": stage,
                            "summary": "The agent requested multiple tools in one turn, which this workflow does not allow.",
                            "intent": "Continue the workflow with one auditable, approved action.",
                            "input_summary": f"Requested {len(calls)} tools in a single turn.",
                            "output_summary": "All requests were rejected and the agent was instructed to retry with one tool.",
                            "input_details": {"Tool requests": len(calls)},
                            "output_details": {"Policy": "Only one tool may run per turn."},
                            "evidence": [],
                            "occurred_at": self._now(),
                        }
                    )
                    trace["updated_at"] = self._now()
                    self._save_trace(trace)
                    continue

                call = calls[0]
                tool_started = perf_counter()
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
                occurred_at = self._now()
                duration_ms = max(round((perf_counter() - tool_started) * 1000), 1)
                trace["events"].append(
                    {
                        "turn": trace["turn"],
                        "type": "tool",
                        "name": call.function.name,
                        "stage": stage,
                        "ok": bool(result.get("ok")),
                        "error": result.get("error"),
                        "summary": self._tool_summary(call.function.name),
                        "intent": self._tool_intent(call.function.name, arguments),
                        "input_summary": self._input_summary(
                            call.function.name,
                            arguments,
                            chunk_count=len(chunks),
                        ),
                        "output_summary": self._output_summary(
                            call.function.name,
                            result,
                            state=state,
                            chunk_count=len(chunks),
                        ),
                        "input_details": self._input_details(call.function.name, arguments),
                        "output_details": self._output_details(
                            call.function.name,
                            result,
                            state=state,
                            chunk_count=len(chunks),
                        ),
                        "evidence": self._evidence_references(call.function.name, arguments, result),
                        "duration_ms": duration_ms,
                        "occurred_at": occurred_at,
                    }
                )
                trace["updated_at"] = occurred_at
                if state["submitted"] is not None:
                    trace["status"] = "completed"
                    if stage and stage not in trace["completed_stages"]:
                        trace["completed_stages"].append(stage)
                    trace["completed_at"] = self._now()
                    self._save_trace(trace)
                    return AgentOutcome(
                        value=state["submitted"],
                        warnings=warnings,
                        events=trace["events"],
                    )
                self._save_trace(trace)

        trace["status"] = "paused"
        trace["updated_at"] = self._now()
        trace["error"] = "turn_limit"
        self._save_trace(trace)
        raise AIResponseError(
            f"{self.definition.name} reached the {self.settings.agent_max_turns}-turn limit without a valid result."
        )

    def _internal_tool_definitions(self, chunk_count: int) -> list[dict[str, Any]]:
        # Keep the provider-facing tool schema deliberately shallow. Some supported
        # model gateways reject JSON schemas nested more than ten levels deep, while
        # clinical result contracts (notably SDTM record plans) legitimately exceed
        # that limit. The agent receives the exact contract from
        # inspect_workflow_contract and the submitted object is still validated in
        # full by Pydantic in _run_internal_tool.
        submission_parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "result": {
                    "type": "object",
                    "description": (
                        "Complete structured result matching the exact schema returned by "
                        "inspect_workflow_contract. Backend validation remains authoritative."
                    ),
                    "additionalProperties": True,
                }
            },
            "required": ["result"],
            "additionalProperties": False,
        }
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
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    return {
                        "ok": False,
                        "error": "result must be a JSON object or a JSON-encoded object",
                    }
            if not isinstance(raw, dict):
                return {
                    "ok": False,
                    "error": "result must be a JSON object or a JSON-encoded object",
                }
            try:
                validated = self.result_model.model_validate(raw)
            except ValidationError as exc:
                return {
                    "ok": False,
                    "error": "Result schema validation failed.",
                    "problems": exc.errors(include_url=False),
                }
            problems = verify_result(self.definition.workflow, validated)
            if self.result_validator is not None:
                try:
                    self.result_validator(validated)
                except (TypeError, ValueError) as exc:
                    problems.append(str(exc))
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
        normalized = payload if isinstance(payload, dict) else {"ok": True, "result": payload}
        return self._compact_remote_tool_result(call.function.name, normalized)

    @classmethod
    def _compact_remote_tool_result(cls, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Remove non-semantic CDISC navigation metadata before the next model turn.

        CDISC dataset responses repeat large hyperlink collections for the dataset and
        every variable. Those links are useful to an interactive API client but do not
        inform an SDTM mapping decision. Keeping all clinical metadata while removing
        only `_links` prevents the reference response from dominating the model context.
        """

        if name not in CDISC_TOOLS:
            return payload
        compacted, removed = cls._without_navigation_links(payload)
        if not isinstance(compacted, dict):
            compacted = {"ok": True, "result": compacted}
        if removed:
            compacted["reference_response"] = {
                "complete_metadata": True,
                "navigation_link_fields_omitted": removed,
            }
        return compacted

    @classmethod
    def _without_navigation_links(cls, value: Any) -> tuple[Any, int]:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            removed = 0
            for key, item in value.items():
                if key == "_links":
                    removed += 1
                    continue
                compacted, child_removed = cls._without_navigation_links(item)
                result[key] = compacted
                removed += child_removed
            return result, removed
        if isinstance(value, list):
            result = []
            removed = 0
            for item in value:
                compacted, child_removed = cls._without_navigation_links(item)
                result.append(compacted)
                removed += child_removed
            return result, removed
        return value, 0

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
    def _tool_summary(name: str) -> str:
        summaries = {
            "inspect_workflow_contract": "Reviewed the workflow contract, validation rules, and expected result structure.",
            "read_source_chunk": "Read one bounded section of the submitted source material.",
            "submit_result": "Submitted the structured draft for schema and cross-reference validation.",
        }
        return summaries.get(
            name,
            "Queried an approved read-only reference service to support the draft.",
        )

    @staticmethod
    def _tool_intent(name: str, arguments: dict[str, Any]) -> str:
        if name == "inspect_workflow_contract":
            return "Understand the required output structure and validation gates before drafting."
        if name == "read_source_chunk":
            index = arguments.get("index", "requested")
            return f"Review source chunk {index} so the draft is grounded in the submitted material."
        if name == "submit_result":
            return "Validate the complete structured draft and finish the current workflow stage."
        return f"Use the approved {name.replace('_', ' ')} reference service to resolve or support draft details."

    @classmethod
    def _input_details(cls, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "inspect_workflow_contract":
            return {"Parameters": "None"}
        if name == "read_source_chunk":
            return {"Chunk requested": arguments.get("index", "Invalid or missing")}
        if name == "submit_result":
            draft = arguments.get("result")
            if not isinstance(draft, dict):
                return {"Draft payload": "Invalid or missing"}
            details: dict[str, Any] = {
                "Top-level fields": len(draft),
                "Field names": list(draft)[:12],
            }
            collections = {
                key: len(value)
                for key, value in draft.items()
                if isinstance(value, list)
            }
            if collections:
                details["Collection sizes"] = collections
            return details

        details = {}
        for key, value in list(arguments.items())[:12]:
            details[key.replace("_", " ").title()] = cls._safe_trace_value(key, value)
        return details or {"Parameters": "None"}

    @classmethod
    def _output_details(
        cls,
        name: str,
        result: dict[str, Any],
        *,
        state: dict[str, Any],
        chunk_count: int,
    ) -> dict[str, Any]:
        if result.get("ok") is False:
            details: dict[str, Any] = {
                "Status": "Rejected",
                "Reason": str(result.get("error", "The tool did not accept the request."))[:500],
            }
            unread = result.get("unread")
            if isinstance(unread, list):
                details["Unread source chunks"] = unread[:20]
            problems = result.get("problems")
            if isinstance(problems, list):
                details["Validation issue count"] = len(problems)
                details["Validation issues"] = [cls._problem_text(item) for item in problems[:8]]
            return details

        if name == "inspect_workflow_contract":
            schema = result.get("result_schema")
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            rules = result.get("submission_rules")
            return {
                "Status": "Loaded",
                "Workflow": result.get("workflow", "Unknown"),
                "Available source chunks": result.get("source_chunks", chunk_count),
                "Required result fields": list(properties)[:20],
                "Submission rules": rules[:10] if isinstance(rules, list) else [],
            }
        if name == "read_source_chunk":
            return {
                "Status": "Reviewed",
                "Chunk": f"{result.get('index')} of {result.get('total', chunk_count)}",
                "Chunks reviewed": len(state["read_chunks"]),
                "Chunks remaining": max(chunk_count - len(state["read_chunks"]), 0),
                "Source text": "Used by the agent but omitted from the trace.",
            }
        if name == "submit_result":
            return {
                "Schema validation": "Passed",
                "Cross-reference validation": "Passed",
                "Draft status": "Accepted",
            }

        details = {"Status": "Completed"}
        for key, value in result.items():
            if key in {"ok", "error", "content", "text", "body", "payload", "result"}:
                if key == "result":
                    details["Result"] = cls._safe_trace_value(key, value)
                continue
            details[key.replace("_", " ").title()] = cls._safe_trace_value(key, value)
            if len(details) >= 10:
                break
        return details

    @staticmethod
    def _evidence_references(
        name: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> list[str]:
        if name == "inspect_workflow_contract":
            return [f"Workflow contract · {result.get('workflow', 'selected workflow')}"]
        if name == "read_source_chunk":
            return [f"Submitted source · chunk {result.get('index', arguments.get('index', '?'))} of {result.get('total', '?')}"]
        if name == "submit_result":
            if result.get("ok") is False:
                return ["Backend schema and cross-reference validators"]
            return [
                "All submitted source chunks",
                "Backend schema validation",
                "Deterministic cross-reference verification",
            ]
        return [f"Approved external reference tool · {name.replace('_', ' ')}"]

    @staticmethod
    def _safe_trace_value(key: str, value: Any) -> Any:
        normalized = key.casefold()
        if any(token in normalized for token in ("content", "text", "body", "document", "payload")):
            return "Hidden from trace"
        if isinstance(value, str):
            return value[:240] + ("…" if len(value) > 240 else "")
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        if isinstance(value, list):
            if all(isinstance(item, (str, bool, int, float)) or item is None for item in value[:8]):
                return value[:8]
            return f"{len(value)} item(s)"
        if isinstance(value, dict):
            return f"{len(value)} field(s)"
        return str(value)[:240]

    @staticmethod
    def _problem_text(problem: Any) -> str:
        if isinstance(problem, str):
            return problem[:500]
        if isinstance(problem, dict):
            location = ".".join(str(item) for item in problem.get("loc", []))
            message = str(problem.get("msg", problem.get("type", "Validation issue")))
            return f"{location}: {message}"[:500] if location else message[:500]
        return str(problem)[:500]

    @staticmethod
    def _input_summary(name: str, arguments: dict[str, Any], *, chunk_count: int) -> str:
        if name == "inspect_workflow_contract":
            return "No parameters; the contract is supplied by the selected workflow."
        if name == "read_source_chunk":
            index = arguments.get("index")
            return f"Requested source chunk {index} of {chunk_count}."
        if name == "submit_result":
            result = arguments.get("result")
            if isinstance(result, dict):
                fields = list(result)[:8]
                suffix = "…" if len(result) > len(fields) else ""
                return f"Submitted {len(result)} top-level fields: {', '.join(fields)}{suffix}."
            return "Submitted a draft result for validation."
        parameter_names = sorted(arguments)
        if not parameter_names:
            return "No parameters were supplied."
        return f"Supplied parameters: {', '.join(parameter_names)}. Values remain hidden in the source-safe trace."

    @staticmethod
    def _output_summary(
        name: str,
        result: dict[str, Any],
        *,
        state: dict[str, Any],
        chunk_count: int,
    ) -> str:
        if result.get("ok") is False:
            return "The request was not accepted; review the recorded error before the next turn."
        if name == "inspect_workflow_contract":
            schema = result.get("result_schema")
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            rules = result.get("submission_rules")
            rule_count = len(rules) if isinstance(rules, list) else 0
            return f"Loaded {len(properties)} top-level result fields and {rule_count} submission rules."
        if name == "read_source_chunk":
            index = result.get("index")
            remaining = max(chunk_count - len(state["read_chunks"]), 0)
            return f"Reviewed source chunk {index}; {remaining} chunk(s) remain."
        if name == "submit_result":
            return "The draft passed schema and cross-reference validation and was accepted."

        facts: list[str] = []
        for key, value in result.items():
            if key in {"ok", "error"}:
                continue
            label = key.replace("_", " ")
            if isinstance(value, list):
                facts.append(f"{label}: {len(value)} item(s)")
            elif isinstance(value, dict):
                facts.append(f"{label}: {len(value)} field(s)")
            elif isinstance(value, (bool, int, float)):
                facts.append(f"{label}: {value}")
            if len(facts) == 4:
                break
        return "; ".join(facts) + "." if facts else "The reference service completed successfully."

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

    def _load_trace(self) -> dict[str, Any]:
        if self.progress_path is None or not self.progress_path.is_file():
            return {}
        try:
            loaded = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def _review_stage_matches(saved_stage: str, agent_stage: str) -> bool:
    aliases = {
        "edc_source": "edc source normalization",
        "domain_mapping": "domain mapping",
        "variable_mapping": "variable & value-level mapping",
        "tlf_inventory": "output inventory",
        "tlf_shell": "analysis & display specification",
        "tlf_programming": "programming augmentation",
    }
    return aliases.get(saved_stage, saved_stage).casefold() == agent_stage.casefold()


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
    elif workflow == "sdtm-source-normalization":
        dataset_names = [dataset.name.strip().casefold() for dataset in value.datasets]
        if any(not name for name in dataset_names):
            problems.append("EDC source dataset names cannot be empty.")
        if len(dataset_names) != len(set(dataset_names)):
            problems.append("EDC source dataset names must be unique.")
        codelist_names = [item.name.strip().casefold() for item in value.codelists]
        if len(codelist_names) != len(set(codelist_names)):
            problems.append("EDC source codelist names must be unique.")
        known_codelists = set(codelist_names)
        for dataset in value.datasets:
            variables = [variable.name.strip().casefold() for variable in dataset.variables]
            if any(not name for name in variables):
                problems.append(f"Dataset {dataset.name} has an empty variable name.")
            if len(variables) != len(set(variables)):
                problems.append(f"Dataset {dataset.name} has duplicate variable names.")
            for key in dataset.key_variables:
                if key.strip().casefold() not in set(variables):
                    problems.append(f"Dataset {dataset.name} key {key} does not reference a source variable.")
            for variable in dataset.variables:
                if variable.codelist and variable.codelist.strip().casefold() not in known_codelists:
                    problems.append(
                        f"Variable {dataset.name}.{variable.name} references unknown codelist {variable.codelist}."
                    )
    elif workflow == "sdtm-domain-mapping":
        mappings = [
            (mapping.source_dataset.casefold(), mapping.target_domain.upper())
            for mapping in value.domain_mappings
        ]
        if len(mappings) != len(set(mappings)):
            problems.append("Source dataset to target domain mappings must be unique.")
        unmapped = [item.source_dataset.casefold() for item in value.unmapped_datasets]
        if len(unmapped) != len(set(unmapped)):
            problems.append("Not-mapped source dataset dispositions must be unique.")
        mapped_sources = {source for source, _target in mappings}
        overlap = sorted(mapped_sources & set(unmapped))
        if overlap:
            problems.append(
                "Source datasets cannot be both mapped and marked not mapped: "
                f"{', '.join(overlap)}."
            )
        if "3.4" not in value.standard:
            problems.append("The draft must identify SDTMIG 3.4 as its baseline.")
    elif workflow in {"sdtm-variable-mapping", "sdtm"}:
        domains = [dataset.domain.upper() for dataset in value.datasets]
        if len(domains) != len(set(domains)):
            problems.append("SDTM domain identifiers must be unique.")
        for dataset in value.datasets:
            variables = [variable.name.upper() for variable in dataset.variables]
            if len(variables) != len(set(variables)):
                problems.append(f"Domain {dataset.domain} has duplicate variable names.")
            step_ids = [step.step_id.casefold() for step in dataset.record_plan.steps]
            if len(step_ids) != len(set(step_ids)):
                problems.append(f"Domain {dataset.domain} record-plan step identifiers must be unique.")
            if dataset.record_plan.output_step.casefold() not in set(step_ids):
                problems.append(f"Domain {dataset.domain} record-plan output_step does not reference a step.")
            available_steps: set[str] = set()
            for step in dataset.record_plan.steps:
                references = [
                    *step.inputs,
                    *([step.left] if step.left else []),
                    *([step.right] if step.right else []),
                ]
                if any(reference.casefold() not in available_steps for reference in references):
                    problems.append(f"Domain {dataset.domain} step {step.step_id} references a later or unknown step.")
                available_steps.add(step.step_id.casefold())
            for variable in dataset.variables:
                identities = [
                    (source.dataset.casefold(), source.variable.casefold(), source.role)
                    for source in variable.sources
                ]
                if len(identities) != len(set(identities)):
                    problems.append(f"Variable {dataset.domain}.{variable.name} has duplicate source references.")
                if variable.mapping_type == "direct" and len(variable.sources) != 1:
                    problems.append(f"Variable {dataset.domain}.{variable.name} direct mapping needs one source.")
                if variable.mapping_type == "assigned" and variable.sources:
                    problems.append(f"Variable {dataset.domain}.{variable.name} assigned mapping cannot have sources.")
                if not variable.sources:
                    origin = variable.origin.strip().casefold()
                    if not any(token in origin for token in ("assigned", "derived", "protocol", "system", "sponsor")):
                        problems.append(
                            f"Sourceless variable {dataset.domain}.{variable.name} needs an assigned or derived origin."
                        )
                    if not variable.mapping_expression.strip() or variable.mapping_expression.strip().casefold() == "direct":
                        problems.append(
                            f"Sourceless variable {dataset.domain}.{variable.name} needs explicit mapping logic."
                        )
        if "3.4" not in value.standard:
            problems.append("The draft must identify SDTMIG 3.4 as its baseline.")
        if "2.1" not in value.define_standard:
            problems.append("The draft must identify Define-XML 2.1 as its baseline.")
        if workflow == "sdtm":
            known_domains = set(domains)
            mapped_domains = {mapping.target_domain.upper() for mapping in value.domain_mappings}
            for domain in mapped_domains - known_domains:
                problems.append(f"Domain mapping references target domain {domain} without a variable mapping.")
            for dataset in value.datasets:
                mapped_sources = {
                    mapping.source_dataset.casefold()
                    for mapping in value.domain_mappings
                    if mapping.target_domain.upper() == dataset.domain.upper()
                }
                for variable in dataset.variables:
                    for source in [*variable.sources, *(item for vlm in variable.value_level_metadata for item in vlm.sources)]:
                        if source.dataset.casefold() not in mapped_sources:
                            problems.append(
                                f"Variable {dataset.domain}.{variable.name} references source dataset "
                                f"{source.dataset} without a domain mapping."
                            )
            rule_ids = [rule.rule_id.casefold() for rule in value.rule_augmentations]
            if len(rule_ids) != len(set(rule_ids)):
                problems.append("SDTM rule identifiers must be unique.")
            rule_targets = [
                (rule.target_domain.upper(), rule.target_variable.upper())
                for rule in value.rule_augmentations
            ]
            if len(rule_targets) != len(set(rule_targets)):
                problems.append("Each SDTM domain-variable pair must have exactly one augmented rule.")
            variable_targets = {
                (dataset.domain.upper(), variable.name.upper())
                for dataset in value.datasets
                for variable in dataset.variables
            }
            for domain, variable in set(rule_targets) - variable_targets:
                problems.append(f"Rule target {domain}.{variable} does not exist in variable mappings.")
            for domain, variable in variable_targets - set(rule_targets):
                problems.append(f"Variable {domain}.{variable} is missing an augmented rule.")
            for rule in value.rule_augmentations:
                try:
                    normalize_r_mapping_expression(rule.r_expression)
                except ValueError as exc:
                    problems.append(
                        f"Rule {rule.rule_id} for {rule.target_domain}.{rule.target_variable} has an invalid R expression: {exc}"
                    )
    elif workflow == "sdtm-rule-augmentation":
        rule_ids = [rule.rule_id.casefold() for rule in value.rule_augmentations]
        if len(rule_ids) != len(set(rule_ids)):
            problems.append("SDTM rule identifiers must be unique.")
        rule_targets = [
            (rule.target_domain.upper(), rule.target_variable.upper())
            for rule in value.rule_augmentations
        ]
        if len(rule_targets) != len(set(rule_targets)):
            problems.append("Each SDTM domain-variable pair must have exactly one augmented rule.")
        for rule in value.rule_augmentations:
            try:
                normalize_r_mapping_expression(rule.r_expression)
            except ValueError as exc:
                problems.append(
                    f"Rule {rule.rule_id} for {rule.target_domain}.{rule.target_variable} has an invalid R expression: {exc}"
                )
        if "3.4" not in value.standard:
            problems.append("The draft must identify SDTMIG 3.4 as its baseline.")
    elif workflow in {"tlf-output-inventory", "tlf-analysis-specification", "tlf"}:
        output_ids = [item.output_id.casefold() for item in value.outputs]
        if len(output_ids) != len(set(output_ids)):
            problems.append("TLF output_id values must be unique (case-insensitive).")
        if workflow in {"tlf-analysis-specification", "tlf"}:
            for item in value.outputs:
                column_ids = [column.column_id.casefold() for column in item.columns]
                row_ids = [row.row_id.casefold() for row in item.rows]
                if len(column_ids) != len(set(column_ids)):
                    problems.append(f"TLF output {item.output_id} has duplicate column identifiers.")
                if len(row_ids) != len(set(row_ids)):
                    problems.append(f"TLF output {item.output_id} has duplicate row identifiers.")
                known_datasets = {dataset.casefold() for dataset in item.analysis_datasets}
                for variable in item.source_variables:
                    if variable.dataset.casefold() not in known_datasets:
                        problems.append(
                            f"TLF output {item.output_id} source variable {variable.dataset}.{variable.variable} "
                            "references an undeclared analysis dataset."
                        )
        if workflow == "tlf":
            program_ids = [program.output_id.casefold() for program in value.programs]
            if len(program_ids) != len(set(program_ids)):
                problems.append("TLF program output identifiers must be unique (case-insensitive).")
            missing = set(output_ids) - set(program_ids)
            extra = set(program_ids) - set(output_ids)
            for output_id in sorted(missing):
                problems.append(f"TLF output {output_id} is missing a programming augmentation.")
            for output_id in sorted(extra):
                problems.append(f"TLF program {output_id} does not reference a defined output.")
            outputs_by_id = {output.output_id.casefold(): output for output in value.outputs}
            for program in value.programs:
                input_datasets = {dataset.casefold() for dataset in program.input_datasets}
                adam_links = [
                    (source.dataset.casefold(), source.variable.casefold())
                    for source in program.adam_sources
                ]
                if len(adam_links) != len(set(adam_links)):
                    problems.append(f"TLF program {program.output_id} has duplicate ADaM schema links.")
                for source in program.adam_sources:
                    if source.dataset.casefold() not in input_datasets:
                        problems.append(
                            f"TLF program {program.output_id} ADaM link {source.dataset}.{source.variable} "
                            "references an undeclared input dataset."
                        )
                output = outputs_by_id.get(program.output_id.casefold())
                if output is not None:
                    expected_links = {
                        (source.dataset.casefold(), source.variable.casefold())
                        for source in output.source_variables
                    }
                    actual_links = set(adam_links)
                    for dataset, variable in sorted(expected_links - actual_links):
                        problems.append(
                            f"TLF program {program.output_id} is missing the approved ADaM schema link "
                            f"{dataset.upper()}.{variable.upper()}."
                        )
                    for dataset, variable in sorted(actual_links - expected_links):
                        problems.append(
                            f"TLF program {program.output_id} ADaM schema link "
                            f"{dataset.upper()}.{variable.upper()} is not defined in the approved shell."
                        )
    elif workflow == "tlf-programming-augmentation":
        program_ids = [program.output_id.casefold() for program in value.programs]
        if len(program_ids) != len(set(program_ids)):
            problems.append("TLF program output identifiers must be unique (case-insensitive).")
        for program in value.programs:
            input_datasets = {dataset.casefold() for dataset in program.input_datasets}
            adam_links = [
                (source.dataset.casefold(), source.variable.casefold())
                for source in program.adam_sources
            ]
            if len(adam_links) != len(set(adam_links)):
                problems.append(f"TLF program {program.output_id} has duplicate ADaM schema links.")
            for source in program.adam_sources:
                if source.dataset.casefold() not in input_datasets:
                    problems.append(
                        f"TLF program {program.output_id} ADaM link {source.dataset}.{source.variable} "
                        "references an undeclared input dataset."
                    )
    return list(dict.fromkeys(problems))
