#!/bin/bash
set -e
echo "Validating MVP..."
python -m pytest tests/ -v
echo "MVP validation completed"
