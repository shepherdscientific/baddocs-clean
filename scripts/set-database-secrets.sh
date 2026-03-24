#!/bin/bash
set -e
echo "Setting database secrets..."
export DATABASE_URL="postgresql://user:pass@localhost/baddocs"
echo "Database secrets set"
