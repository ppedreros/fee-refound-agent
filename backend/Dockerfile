# Backend image, used by both `migrate` (python -m backend.bootstrap) and `backend`.
# Build from the repo root: docker build -f backend/Dockerfile .

FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY backend ./backend
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0
USER app
EXPOSE 8000
# Binds ${PORT:-8000} (settings read PORT), so a host like Render can choose the port.
CMD ["python", "-m", "backend.api"]
