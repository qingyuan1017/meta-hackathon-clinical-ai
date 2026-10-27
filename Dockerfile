# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.29 AS uv

FROM python:3.13-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY openfda_mcp ./openfda_mcp

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENFDA_MCP_ALLOWED_HOSTS="openfda-mcp:8000,localhost:8000,127.0.0.1:8000"

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

ENTRYPOINT ["openfda-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]

