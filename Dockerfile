FROM python:3.11-slim

WORKDIR /app

# System deps (git is needed by the try-it endpoint to clone repos).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (src-layout; no setup.py).
COPY pyproject.toml pyproject.toml
COPY src/ src/
COPY config/ config/
RUN pip install --no-cache-dir -e .

# Non-root user
RUN useradd -m -u 1000 baddocs && chown -R baddocs:baddocs /app
USER baddocs

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Run the FastAPI server (hosts /health, /api/try-it, /api/github/webhook, ...).
CMD ["uvicorn", "baddocs.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
