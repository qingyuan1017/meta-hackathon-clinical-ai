FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLINICALGOV_MCP_TRANSPORT=streamable-http \
    CLINICALGOV_MCP_HOST=0.0.0.0 \
    CLINICALGOV_MCP_PORT=8003

WORKDIR /app
COPY pyproject.toml ./
COPY README.md ./
COPY clinicalgov_mcp ./clinicalgov_mcp
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8003
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import socket; connection = socket.create_connection(('127.0.0.1', 8003), 2); connection.close()"

CMD ["clinicalgov-mcp"]
