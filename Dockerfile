FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml pyproject.toml
COPY setup.py setup.py

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY src/ src/
COPY config/ config/

# Create non-root user
RUN useradd -m -u 1000 baddocs && chown -R baddocs:baddocs /app
USER baddocs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["baddocs-cli", "serve"]
