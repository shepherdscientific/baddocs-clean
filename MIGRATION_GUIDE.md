# Migration Guide

## Upgrading to a New Version

### From v0.x to v1.0

#### Database Migration

```bash
# Backup current database
pg_dump baddocs > backup.sql

# Run migrations
python scripts/run_migrations.py

# Verify migration
python -c "from baddocs.storage import models; print(models.Document.__table__.columns.keys())"
```

#### Configuration Changes

- Update `.env` with new variables
- Review `config/providers.yml` for new providers
- Update `pyproject.toml` dependencies

#### API Changes

- See `API_CHANGES.md` for endpoint modifications
- Update integration code accordingly
