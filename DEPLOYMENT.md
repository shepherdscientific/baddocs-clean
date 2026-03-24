# Deployment Guide

## Docker Deployment

### Building the Docker Image

```bash
docker build -t baddocs:latest .
```

### Running with Docker Compose

```bash
docker-compose up -d
```

## Kubernetes Deployment

See Helm chart in `k8s/` directory.

## Environment Variables

See `.env.example` for all available environment variables.

## Database Setup

```bash
alembic upgrade head
```

## Production Checklist

- [ ] Set `DEBUG=false`
- [ ] Configure proper `SECRET_KEY`
- [ ] Set up database backups
- [ ] Configure logging
- [ ] Set up monitoring
- [ ] Configure HTTPS/TLS
