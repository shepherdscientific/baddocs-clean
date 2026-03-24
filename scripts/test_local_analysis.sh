#!/bin/bash
set -e
echo "Testing local analysis..."
baddocs-cli analyze .
echo "Local analysis test completed"
