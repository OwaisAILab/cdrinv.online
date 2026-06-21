# ─────────────────────────────────────────────────────────────────────────────
#  CDR Intelligence Portal — Dockerfile for Fly.io
#  Stack: Flask 3 + Gunicorn + SQLite (persistent volume) + pandas/numpy
# ─────────────────────────────────────────────────────────────────────────────

# Stage 1: Build — install heavy deps (pandas, numpy, openpyxl) with full toolchain
FROM python:3.11-slim AS builder

WORKDIR /build

# System build deps (needed for cryptography, argon2-cffi native builds)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a prefix dir so we can copy cleanly to runtime stage
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Runtime — lean image, no build tools
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system libs only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source (excludes venv, .git, logs — see .dockerignore)
COPY auth/        ./auth/
COPY core/        ./core/
COPY templates/   ./templates/
COPY static/      ./static/
COPY main.py      .
COPY migrate_db.py .

# ── Persistent data directory ─────────────────────────────────────────────
# Fly.io volume will be mounted at /data
# SQLite DB and uploads live here so they survive restarts/deploys
RUN mkdir -p /data/uploads

# ── Non-root user for security ────────────────────────────────────────────
RUN useradd -m -u 1000 cdrapp && \
    chown -R cdrapp:cdrapp /app /data

USER cdrapp

# ── Environment defaults (override via Fly.io secrets) ───────────────────
ENV FLASK_SECRET_KEY="change-me-use-fly-secrets" \
    DATABASE_URL="sqlite:////data/cdr_portal.db" \
    UPLOAD_FOLDER="/data/uploads" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# ── Startup: run DB migrations then launch gunicorn ───────────────────────
CMD ["sh", "-c", "python migrate_db.py 2>/dev/null || true && \
     gunicorn main:app \
       --bind 0.0.0.0:8080 \
       --workers 2 \
       --threads 2 \
       --timeout 120 \
       --access-logfile - \
       --error-logfile -"]
