# Development Workflow

Guidelines for contributing to BadDocs.

## Setup

1. Fork the repository
2. Clone your fork
3. Create a feature branch: `git checkout -b feature/your-feature`
4. Set up development environment: `make dev-setup`
5. Install pre-commit hooks: `pre-commit install`

## Development

### Running Tests

```bash
# All tests
make test

# Unit tests only
make test-unit

# Integration tests
make test-integration

# With coverage
make test-coverage
```

### Code Quality

```bash
# Format code
make format

# Lint code
make lint

# Type checking
make typecheck
```

## Submitting Changes

1. Ensure all tests pass
2. Add new tests for new functionality
3. Update documentation
4. Commit with descriptive messages
5. Push to your fork
6. Create a pull request
