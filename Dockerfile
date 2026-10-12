FROM ghcr.io/astral-sh/uv:0.12.19 AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY app ./app
COPY public ./public
COPY .streamlit/config.toml .streamlit/config.toml
RUN uv sync --frozen --no-dev --extra app --extra all

EXPOSE 3000
CMD ["sh", "-c", "exec uv run --no-sync python app/serve.py"]
