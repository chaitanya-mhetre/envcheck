# Mostly useful in CI images; locally, prefer `uvx envcheck` so it checks your real machine.
# docker build -t envcheck . && docker run --rm -v "$PWD:/work" envcheck --ci
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --all-extras
WORKDIR /work
ENTRYPOINT ["/app/.venv/bin/envcheck"]
