FROM python:3.12-slim AS base

LABEL maintainer="Ronald Jonkers"
LABEL description="ExecutiveAI — AI Executive Assistant"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY . .

RUN mkdir -p /app/data /app/logs /app/config

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "executiveai.main:app", "--host", "0.0.0.0", "--port", "8000"]
