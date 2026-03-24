# Development Workflow

## Setting up Development Environment

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Running Tests with Coverage

```bash
pytest --cov=src
```

## Code Quality

```bash
black src/
flake8 src/
mypy src/
```

## Building Documentation

```bash
mkdocs serve
```
