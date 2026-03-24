# Docker Testing Guide

## Running Tests in Docker

### Unit Tests

```bash
docker-compose -f docker-compose.test.yml run --rm test-unit
```

### Integration Tests

```bash
docker-compose -f docker-compose.test.yml run --rm test-integration
```

### All Tests

```bash
docker-compose -f docker-compose.test.yml up
```

## Development Container

```bash
docker-compose -f docker-compose.dev.yml up
```

This starts a development environment with:
- PostgreSQL database
- Redis cache
- BadDocs application
- Hot-reload enabled
