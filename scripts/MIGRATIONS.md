# Database Migrations

Guide for running database migrations.

## Running Migrations

```bash
python scripts/run_migrations.py
```

## Creating New Migrations

```bash
python -m alembic revision --autogenerate -m "description"
```
