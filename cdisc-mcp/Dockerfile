FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CDISC_MCP_TRANSPORT=streamable-http \
    CDISC_MCP_HOST=0.0.0.0 \
    CDISC_MCP_PORT=8001

WORKDIR /app
COPY pyproject.toml ./
COPY README.md ./
COPY cdisc_mcp ./cdisc_mcp
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import socket; connection = socket.create_connection(('127.0.0.1', 8001), 2); connection.close()"

CMD ["cdisc-library-mcp"]
