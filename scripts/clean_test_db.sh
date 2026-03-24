#!/bin/bash
set -e
echo "Cleaning test database..."
python -c "from baddocs.storage import models; models.Base.metadata.drop_all()"
echo "Test database cleaned"
