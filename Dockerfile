# One image, three entry points:
#   API:       uvicorn ops.api:app --host 0.0.0.0 --port 8000
#   worker:    ops worker --queue sqs --provider bedrock
#   migration: ops migrate   (one-off ECS task with its own role)
# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/ frontend/
RUN if [ -f frontend/package-lock.json ]; then \
      npm --prefix frontend ci && npm --prefix frontend run build; \
    else mkdir -p frontend/dist; fi

FROM python:3.12-slim-bookworm AS app
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" DEPLOY_ENV=aws AUTH_MODE=cognito
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-default-groups --no-install-project
COPY backend/ backend/
COPY db/ db/
COPY alembic.ini ./
COPY configs/ configs/
COPY data/fixtures/ data/fixtures/
COPY data/scenarios/ data/scenarios/
RUN uv sync --locked --no-default-groups
COPY --from=frontend /src/frontend/dist frontend/dist
RUN useradd --system --uid 10001 ops && chown -R ops /app/data
USER ops
EXPOSE 8000
CMD ["uvicorn", "ops.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
