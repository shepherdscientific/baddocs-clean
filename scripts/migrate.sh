#!/bin/bash
# Database migration script

set -e

echo "Running database migrations..."
python scripts/run_migrations.py
echo "Migrations completed successfully"
