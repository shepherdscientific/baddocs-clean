# Deployment Guide

This guide covers deploying BadDocs in various environments.

## Local Development

### Prerequisites
- Python 3.9+
- PostgreSQL 12+
- Node.js 16+ (for UI)

### Setup

```bash
# Clone repository
git clone <repo-url>
cd baddocs

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .[dev]

# Setup database
psql -U postgres -f scripts/init_db.sql

# Run migrations
python scripts/run_migrations.py

# Start server
baddocs-cli serve
```

## Docker Deployment

### Build

```bash
docker build -t baddocs:latest .
```

### Run

```bash
docker run -d \
  -e DATABASE_URL=postgresql://user:pass@db:5432/baddocs \
  -e ANTHROPIC_API_KEY=your_key \
  -p 8000:8000 \
  baddocs:latest
```

## Production Deployment

Refer to `DEPLOYMENT.md` for detailed production deployment instructions.
