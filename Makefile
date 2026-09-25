.PHONY: check lint fmt type test build services doctor integration
check: lint type test
lint:
	uv run ruff check .
	uv run ruff format --check .
fmt:
	uv run ruff format .
	uv run ruff check --fix .
type:
	uv run mypy
test:
	uv run pytest -q
build:
	uv build
services:
	docker compose up -d --wait
doctor:
	uv run envcheck
integration: services
	uv run pytest -q -m integration
