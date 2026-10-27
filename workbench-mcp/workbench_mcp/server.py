from __future__ import annotations

import argparse
from typing import Any

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from . import __version__
from .client import WorkbenchClient
from .config import get_settings


class TextInput(BaseModel):
    filename: str = Field(description="A safe filename with a use-case-supported text extension.")
    content: str = Field(description="Synthetic or de-identified source text; never a local file path.")


mcp = MCPServer(
    "Clinical AI Artifact Workbench",
    version=__version__,
    instructions=(
        "Discover a use case before submitting work. Submit only synthetic or de-identified text. "
        "Poll jobs until completion. Human revisions must preserve the returned JSON schema; updating a result "
        "rebuilds artifacts without another model call. Binary PDF/XLSX inputs must use the REST or web UI."
    ),
)


def _client() -> WorkbenchClient:
    return WorkbenchClient.from_settings()


@mcp.tool()
async def workbench_list_use_cases() -> list[dict[str, Any]]:
    """List the five use cases, accepted inputs, skill names, outputs, dependencies, and result schemas."""

    return await _client().request("GET", "/use-cases")


@mcp.tool()
async def workbench_get_use_case(use_case: str) -> dict[str, Any]:
    """Get one use-case contract and its editable structured-result JSON Schema."""

    return await _client().request("GET", f"/use-cases/{use_case}")


@mcp.tool()
async def workbench_list_agents() -> list[dict[str, Any]]:
    """List the five backend agents, their workflows, bounded tools, and turn limits."""

    return await _client().request("GET", "/agents")


@mcp.tool()
async def workbench_get_agent(use_case: str) -> dict[str, Any]:
    """Get the agent contract that executes one use case."""

    return await _client().request("GET", f"/agents/{use_case}")


@mcp.tool()
async def workbench_submit_text_job(
    use_case: str,
    inputs: list[TextInput],
    options: dict[str, Any],
    deidentified_acknowledged: bool,
) -> dict[str, Any]:
    """Submit textual inputs. Use REST/UI instead when a workflow requires a PDF or XLSX binary."""

    if not deidentified_acknowledged:
        raise ValueError("Explicit synthetic/de-identified-data acknowledgement is required.")
    return await _client().submit_text_job(
        use_case,
        inputs=[item.model_dump() for item in inputs],
        options=options,
        acknowledged=True,
    )


@mcp.tool()
async def workbench_list_jobs(use_case: str | None = None, status: str | None = None) -> dict[str, Any]:
    """List local jobs, optionally filtered by use case and status."""

    params = {key: value for key, value in {"workflow": use_case, "status": status}.items() if value}
    return await _client().request("GET", "/jobs", params=params)


@mcp.tool()
async def workbench_get_job(job_id: str) -> dict[str, Any]:
    """Read job status, structured result, warnings, and artifact metadata."""

    return await _client().request("GET", f"/jobs/{job_id}")


@mcp.tool()
async def workbench_get_agent_progress(job_id: str) -> dict[str, Any]:
    """Read a source-free summary of agent turns, tool outcomes, and source coverage."""

    return await _client().request("GET", f"/jobs/{job_id}/agent")


@mcp.tool()
async def workbench_update_job_result(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Save a human-approved structured revision and rebuild artifacts without rerunning the model."""

    return await _client().request("PUT", f"/jobs/{job_id}/result", json={"result": result})


def _arguments() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the Clinical AI Workbench MCP adapter.")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default=settings.workbench_mcp_transport)
    parser.add_argument("--host", default=settings.workbench_mcp_host)
    parser.add_argument("--port", type=int, default=settings.workbench_mcp_port)
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
