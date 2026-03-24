#!/bin/bash
set -e
echo "Running Docker migrations..."
docker-compose -f docker-compose.test.yml run --rm app python scripts/run_migrations.py
echo "Docker migrations completed"
