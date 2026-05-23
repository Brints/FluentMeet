# ============================================================
# Stage 1 — Builder: install dependencies in a clean layer
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System deps needed to compile psycopg2, cryptography, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Sync dependencies to a virtual environment
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ============================================================
# Stage 2 — Runtime: lean production image
# ============================================================
FROM python:3.11-slim AS runtime

# Only the PostgreSQL client lib is needed at runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/
COPY templates/ ./templates/

# Own files by appuser
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Run using the python interpreter inside the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Run with uvicorn — 4 workers for production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
