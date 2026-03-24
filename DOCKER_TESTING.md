# Docker Testing

## Running Tests in Docker

```bash
docker-compose -f docker-compose.test.yml up
```

## Running Specific Tests

```bash
docker exec baddocs pytest tests/unit/test_cli.py
```

## Debugging in Docker

```bash
docker exec -it baddocs /bin/bash
```
