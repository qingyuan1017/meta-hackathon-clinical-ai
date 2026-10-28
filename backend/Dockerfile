FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG CORE_COMMIT=2a90a3872a7e3b07c15abe84744026c94a7a04b0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && git init /opt/cdisc-core \
    && git -C /opt/cdisc-core remote add origin https://github.com/cdisc-org/cdisc-rules-engine.git \
    && git -C /opt/cdisc-core fetch --depth 1 origin ${CORE_COMMIT} \
    && git -C /opt/cdisc-core checkout --detach FETCH_HEAD \
    && rm -rf /opt/cdisc-core/.git \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
