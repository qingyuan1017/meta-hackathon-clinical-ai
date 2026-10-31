FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends r-base r-cran-dplyr r-cran-readr r-cran-haven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY runner ./runner
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 runner

USER runner
EXPOSE 8010
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')"
CMD ["uvicorn", "runner.main:app", "--host", "0.0.0.0", "--port", "8010"]

