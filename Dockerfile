# Multi-stage build for Zoid FastAPI backend
# Stage 1: Builder — install dependencies
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Use pip with the project dependencies
# Extract dependencies from pyproject.toml and install
RUN pip install --upgrade pip && \
    pip install fastapi==0.141.1 uvicorn[standard]==0.53.0 pydantic==2.13.5 \
    pydantic-settings==2.15.0 python-dotenv==1.2.3 email-validator==2.3.0 \
    sqlalchemy==2.0.54 asyncpg==0.31.0 alembic==1.20.0 httpx==0.28.1 \
    pwdlib==0.3.1 argon2-cffi==25.1.0 PyJWT==2.14.0 \
    stripe==15.6.1 resend==2.47.0 cloudinary==1.46.2 boto3==1.43.24 \
    redis==8.1.0 fastapi-limiter==0.2.0 pyrate-limiter==4.5.0

# Stage 2: Runtime — minimal image
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose API port
EXPOSE 8000

# Run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
