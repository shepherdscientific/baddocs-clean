#!/bin/bash
# Clear database script

set -e

echo "Clearing database..."
python -c "from baddocs.storage import models; models.Base.metadata.drop_all()"
echo "Database cleared"
