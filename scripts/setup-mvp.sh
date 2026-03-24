#!/bin/bash
set -e
echo "Setting up MVP environment..."
python scripts/run_migrations.py
echo "MVP setup completed"
