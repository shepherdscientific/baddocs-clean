#!/bin/bash
# Validate prd.json for duplicate keys
# Usage: ./validate-prd.sh

set -e

PRD_FILE="prd.json"

echo "Validating $PRD_FILE..."

# Check if prd.json exists
if [ ! -f "$PRD_FILE" ]; then
  echo "❌ ERROR: $PRD_FILE not found!"
  exit 1
fi

# Check if prd.json is valid JSON
if ! jq empty "$PRD_FILE" 2>/dev/null; then
  echo "❌ ERROR: $PRD_FILE is not valid JSON!"
  exit 1
fi

# Check for duplicate "passes" keys
if python3 -c "
import json
import sys

with open('$PRD_FILE') as f:
    text = f.read()
    
# Count 'passes' occurrences per story
stories = text.split('\"id\"')
duplicates = []

for i, story in enumerate(stories[1:], 1):  # Skip first split
    passes_count = story.count('\"passes\"')
    if passes_count > 1:
        # Extract story ID
        story_id = story.split('\"')[2] if '\"' in story else f'Story #{i}'
        duplicates.append(f'{story_id} has {passes_count} \"passes\" fields')

if duplicates:
    print('❌ DUPLICATE KEYS FOUND:')
    for dup in duplicates:
        print(f'   {dup}')
    sys.exit(1)
else:
    print('✅ No duplicate keys found')
    sys.exit(0)
"; then
  echo "✅ $PRD_FILE is valid!"
else
  echo ""
  echo "To fix: Use jq to update prd.json (see AGENTS.md)"
  echo "Example: jq '(.userStories[] | select(.id == \"US-XXX\") | .passes) = true' $PRD_FILE > /tmp/prd.json && mv /tmp/prd.json $PRD_FILE"
  exit 1
fi