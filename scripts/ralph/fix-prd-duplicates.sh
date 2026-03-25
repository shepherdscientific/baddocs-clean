#!/bin/bash
# Auto-fix duplicate keys in prd.json
# Usage: ./fix-prd-duplicates.sh

set -e

PRD_FILE="prd.json"

if [ ! -f "$PRD_FILE" ]; then
  echo "❌ ERROR: $PRD_FILE not found!"
  exit 1
fi

echo "Fixing duplicate keys in $PRD_FILE..."

# Use Python to parse JSON properly and remove duplicates
python3 << 'EOF'
import json
import sys

with open('prd.json', 'r') as f:
    data = json.load(f)

# The json.load() automatically handles duplicates by keeping the last value
# So just writing it back out will fix the issue
with open('prd.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')  # Add trailing newline

print("✅ Fixed! Duplicate keys removed (last value kept)")
EOF

# Validate the result
./validate-prd.sh