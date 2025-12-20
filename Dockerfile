FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv pip install --system -e .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "tessera.main:app", "--host", "0.0.0.0", "--port", "8000"]
