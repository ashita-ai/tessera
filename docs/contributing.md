# Contributing

Thank you for your interest in contributing to Tessera!

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management
- Docker (optional, for PostgreSQL)

### Setup

```bash
# Clone the repository
git clone https://github.com/ashita-ai/tessera.git
cd tessera

# Install dependencies
uv sync --all-extras

# Run tests
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest

# Start development server
uv run uvicorn tessera.main:app --reload
```

## Development Workflow

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates

### Code Style

We use:
- **ruff** for linting and formatting
- **mypy** for type checking

```bash
# Format code
uv run ruff format src/

# Lint
uv run ruff check src/

# Type check
uv run mypy src/tessera/
```

### Testing

```bash
# Run all tests
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest

# Run with coverage
uv run pytest --cov=tessera --cov-report=term-missing

# Run specific test
uv run pytest tests/test_schema_diff.py -v
```

### Pre-commit Hooks

Install pre-commit hooks:

```bash
uv run pre-commit install
```

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Ensure all tests pass
5. Update documentation if needed
6. Submit a PR with a clear description

### PR Checklist

- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] All tests pass

## Project Structure

```
src/tessera/
├── api/           # FastAPI routes
├── db/            # SQLAlchemy models
├── models/        # Pydantic schemas
├── services/      # Business logic
├── web/           # Web UI routes
├── templates/     # Jinja2 templates
└── static/        # CSS, JS assets
```

## Key Modules

### Schema Diffing

`services/schema_diff.py` - Core logic for comparing JSON Schemas.

### Contract Publishing

`api/assets.py` - Contract publishing with breaking change detection.

### Proposal Workflow

`api/proposals.py` - Breaking change proposal handling.

## Questions?

- Open an issue on GitHub
- Check existing issues for similar questions

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
