#!/bin/bash
set -e
echo "Cleaning test environment..."
rm -rf .pytest_cache
rm -rf htmlcov
rm -rf .coverage
echo "Test environment cleaned"
