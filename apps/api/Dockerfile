# ──────────────────────────────────────────────────────────────────────
# Palimpsest API — Python 3.12, isolated venv at /opt/venv, non-root user.
# Image is shared with the worker (same deps, different entrypoint).
# ──────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# System dependencies: libpq for asyncpg, curl for healthchecks, git for VCS installs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create the isolated venv (preference: always a venv, never system python)
RUN python -m venv "$VIRTUAL_ENV" \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel

# ── builder stage: install deps ───────────────────────────────────────

FROM base AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install API deps into the venv
COPY apps/api/pyproject.toml /app/pyproject.toml
COPY apps/api/README.md /app/README.md
COPY apps/api/app /app/app

RUN /opt/venv/bin/pip install -e '.'

# Install worker deps on top (shares the same venv)
COPY apps/worker/pyproject.toml /tmp/worker/pyproject.toml
COPY apps/worker/README.md /tmp/worker/README.md
COPY apps/worker/worker /tmp/worker/worker
RUN /opt/venv/bin/pip install -e /tmp/worker

# ── runtime stage ─────────────────────────────────────────────────────

FROM base AS runtime

# Non-root user
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY apps/worker /tmp/worker

# Make sure logs/ and the HF cache mountpoint exist with app:app ownership.
# Named volumes inherit the mountpoint's ownership at first attach, so this
# avoids a chown-on-startup dance for the non-root container.
RUN mkdir -p /app/logs/claude-sessions /cache/huggingface \
    && chown -R app:app /app /opt/venv /tmp/worker /cache

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["/opt/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
