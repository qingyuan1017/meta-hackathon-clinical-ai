"""Command-line entry point for the openFDA MCP server."""

from __future__ import annotations

import argparse
import os
from typing import Literal, cast

from mcp.server.transport_security import TransportSecuritySettings

from .server import mcp


def _csv_environment(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def http_transport_security(port: int) -> TransportSecuritySettings:
    """Build an exact Host/Origin allowlist for local and container traffic."""
    allowed_hosts = _csv_environment("OPENFDA_MCP_ALLOWED_HOSTS")
    if not allowed_hosts:
        allowed_hosts = [
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
            f"openfda-mcp:{port}",
        ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=_csv_environment("OPENFDA_MCP_ALLOWED_ORIGINS"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve openFDA tools over MCP.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    transport = cast(Literal["stdio", "streamable-http"], args.transport)
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            transport_security=http_transport_security(args.port),
        )


if __name__ == "__main__":
    main()

