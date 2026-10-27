FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY workbench_mcp ./workbench_mcp
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import socket; connection = socket.create_connection(('127.0.0.1', 8002), 2); connection.close()"

ENTRYPOINT ["clinical-workbench-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8002"]
