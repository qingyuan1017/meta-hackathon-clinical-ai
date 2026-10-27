from __future__ import annotations

from starlette.testclient import TestClient

from openfda_mcp.__main__ import http_transport_security
from openfda_mcp.server import create_server


def test_default_http_security_allows_exact_local_and_compose_hosts(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENFDA_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("OPENFDA_MCP_ALLOWED_ORIGINS", raising=False)

    security = http_transport_security(8000)

    assert security.enable_dns_rebinding_protection
    assert security.allowed_hosts == [
        "127.0.0.1:8000",
        "localhost:8000",
        "[::1]:8000",
        "openfda-mcp:8000",
    ]
    assert security.allowed_origins == []


def test_http_security_uses_environment_allowlists(monkeypatch) -> None:
    monkeypatch.setenv(
        "OPENFDA_MCP_ALLOWED_HOSTS",
        "openfda-mcp:8000, mcp.example.test:443",
    )
    monkeypatch.setenv(
        "OPENFDA_MCP_ALLOWED_ORIGINS",
        "https://metadata.example.test",
    )

    security = http_transport_security(8000)

    assert security.allowed_hosts == ["openfda-mcp:8000", "mcp.example.test:443"]
    assert security.allowed_origins == ["https://metadata.example.test"]


def test_health_endpoint() -> None:
    server = create_server()
    app = server.streamable_http_app(transport_security=http_transport_security(8000))

    with TestClient(app) as client:
        response = client.get("/health", headers={"Host": "openfda-mcp:8000"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "openfda-mcp",
        "version": "0.1.0",
    }

