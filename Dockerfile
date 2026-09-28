# Test/runtime image for CI's offline job: build with network, run with --network none.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git make patch \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY . .
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1
RUN git config --global --add safe.directory /app
CMD ["sh", "-c", "python -m pytest -q && python scripts/demo.py"]
