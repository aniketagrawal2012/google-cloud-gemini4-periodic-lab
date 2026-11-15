# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Create non-root user for hardened Cloud Run execution
RUN groupadd --system appgroup && useradd --system --gid appgroup appuser

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
       "fastapi>=0.115.0" \
       "uvicorn[standard]>=0.32.0" \
       "pydantic>=2.7.0" \
       "google-auth>=2.35.0" \
       "requests>=2.32.0" \
       "google-cloud-bigquery>=3.25.0"

USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.service:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "75"]
