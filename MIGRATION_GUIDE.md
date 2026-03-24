# Migration Guide

## From v0.x to v1.0

### Breaking Changes

1. Configuration file format has changed
2. API endpoints have been updated
3. Database schema has been migrated

### Migration Steps

1. Back up your database
2. Update configuration files
3. Run database migrations: `alembic upgrade head`
4. Restart the application
