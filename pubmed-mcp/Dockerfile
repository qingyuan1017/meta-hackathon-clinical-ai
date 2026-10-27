FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUBMED_MCP_TRANSPORT=streamable-http \
    PUBMED_MCP_HOST=0.0.0.0 \
    PUBMED_MCP_PORT=8004

WORKDIR /app
COPY pyproject.toml ./
COPY README.md ./
COPY pubmed_mcp ./pubmed_mcp
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8004
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import socket; connection = socket.create_connection(('127.0.0.1', 8004), 2); connection.close()"

CMD ["pubmed-mcp"]
