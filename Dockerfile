# ---------------------------------------------------------------------------
# Stage 1 — build / install dependencies
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build-time system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
COPY ada_bot/ ada_bot/

# Install the package + web extras into /app/venv
RUN python -m venv /app/venv \
    && /app/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /app/venv/bin/pip install --no-cache-dir -e ".[web]"

# ---------------------------------------------------------------------------
# Stage 2 — runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system packages required by Playwright / Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Chromium shared libraries
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libasound2 \
        # Font support
        fonts-liberation \
        # Misc
        wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder
COPY --from=builder /app/venv /app/venv

# Copy source
COPY ada_bot/ ada_bot/
COPY pyproject.toml ./

# Install Playwright browsers (Chromium only to keep image lean)
RUN /app/venv/bin/playwright install chromium 2>/dev/null || true

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Gunicorn: 4 sync workers, 5-minute timeout (audits can be slow)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "4", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "ada_bot.webapp:app"]
